use std::sync::Mutex;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{Manager, RunEvent, State};
use tauri_plugin_global_shortcut::{Code, Modifiers, Shortcut, ShortcutState};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct DaemonState(std::sync::Arc<Mutex<Option<CommandChild>>>);

#[tauri::command]
fn daemon_url() -> String {
    "http://127.0.0.1:8765".to_string()
}

#[tauri::command]
fn ensure_daemon(app: tauri::AppHandle, state: State<'_, DaemonState>) -> Result<String, String> {
    // TCP check
    let alive = std::net::TcpStream::connect_timeout(
        &"127.0.0.1:8765".parse().unwrap(),
        std::time::Duration::from_secs(2),
    ).is_ok();
    if alive {
        return Ok("already running".to_string());
    }
    eprintln!("[raphael] ensure_daemon: not running, spawning...");
    kill_stale_daemon();
    match spawn_daemon(&app) {
        Ok(child) => {
            *state.0.lock().unwrap() = Some(child);
            Ok("started".to_string())
        }
        Err(e) => Err(e),
    }
}

fn kill_stale_daemon() {
    use std::process::Command;
    #[cfg(unix)]
    {
        // 1. Kill any process on port 8765
        if let Ok(output) = Command::new("lsof")
            .args(["-ti", "tcp:8765"])
            .output()
        {
            let pids = String::from_utf8_lossy(&output.stdout);
            for pid in pids.split_whitespace() {
                if let Ok(pid_num) = pid.trim().parse::<u32>() {
                    let my_pid = std::process::id();
                    if pid_num != my_pid {
                        eprintln!("[raphael] killing stale process on :8765 (PID {pid_num})");
                        let _ = Command::new("kill").arg(pid.trim()).output();
                    }
                }
            }
            if !pids.trim().is_empty() {
                std::thread::sleep(std::time::Duration::from_secs(1));
            }
        }
        // 2. Kill any stale raphaeld sidecar processes
        if let Ok(output) = Command::new("pgrep")
            .args(["-f", "raphaeld"])
            .output()
        {
            let pids = String::from_utf8_lossy(&output.stdout);
            for pid in pids.split_whitespace() {
                if let Ok(pid_num) = pid.trim().parse::<u32>() {
                    let my_pid = std::process::id();
                    if pid_num != my_pid {
                        eprintln!("[raphael] killing stale raphaeld (PID {pid_num})");
                        let _ = Command::new("kill").arg(pid.trim()).output();
                    }
                }
            }
        }
        // 3. Kill any other raphael-desktop instances
        if let Ok(output) = Command::new("pgrep")
            .args(["-f", "raphael-desktop"])
            .output()
        {
            let pids = String::from_utf8_lossy(&output.stdout);
            for pid in pids.split_whitespace() {
                if let Ok(pid_num) = pid.trim().parse::<u32>() {
                    let my_pid = std::process::id();
                    if pid_num != my_pid {
                        eprintln!("[raphael] killing stale app instance (PID {pid_num})");
                        let _ = Command::new("kill").arg(pid.trim()).output();
                    }
                }
            }
        }
        std::thread::sleep(std::time::Duration::from_millis(500));
    }
    #[cfg(windows)]
    {
        let _ = Command::new("cmd")
            .args(["/C", "for /f \"tokens=5\" %a in ('netstat -aon ^| findstr :8765 ^| findstr LISTENING') do taskkill /F /PID %a"])
            .output();
        let _ = Command::new("taskkill")
            .args(["/F", "/IM", "raphaeld.exe"])
            .output();
        std::thread::sleep(std::time::Duration::from_secs(1));
    }
}

fn spawn_daemon(app: &tauri::AppHandle) -> Result<CommandChild, String> {
    kill_stale_daemon();

    // 방법 1: 표준 sidecar
    let sidecar_result = (|| -> Result<CommandChild, String> {
        let sidecar = app
            .shell()
            .sidecar("raphaeld")
            .map_err(|e| format!("sidecar lookup: {e}"))?;
        let (mut rx, child) = sidecar
            .args(["--host", "127.0.0.1", "--port", "8765"])
            .spawn()
            .map_err(|e| format!("sidecar spawn: {e}"))?;
        tauri::async_runtime::spawn(async move {
            while let Some(event) = rx.recv().await {
                match event {
                    CommandEvent::Stdout(line) => {
                        eprintln!("[raphaeld] {}", String::from_utf8_lossy(&line))
                    }
                    CommandEvent::Stderr(line) => {
                        eprintln!("[raphaeld] {}", String::from_utf8_lossy(&line))
                    }
                    CommandEvent::Error(e) => eprintln!("[raphaeld error] {e}"),
                    CommandEvent::Terminated(t) => {
                        eprintln!("[raphaeld terminated] code={:?}", t.code);
                        break;
                    }
                    _ => {}
                }
            }
        });
        Ok(child)
    })();

    if sidecar_result.is_ok() {
        eprintln!("[raphael] sidecar spawned (non-blocking)");
        return sidecar_result;
    }

    // 방법 2: sidecar 실패 시 직접 실행 (fallback)
    let raphaeld_path = std::env::current_exe()
        .unwrap_or_default()
        .parent()
        .unwrap_or(std::path::Path::new("."))
        .join("raphaeld");

    if raphaeld_path.exists() {
        eprintln!("[raphael] fallback: direct exec {}", raphaeld_path.display());
        match std::process::Command::new(&raphaeld_path)
            .args(["--host", "127.0.0.1", "--port", "8765"])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
        {
            Ok(_) => eprintln!("[raphael] fallback daemon spawned"),
            Err(e) => eprintln!("[raphael] fallback spawn failed: {e}"),
        }
    }

    sidecar_result
}

fn toggle_main_window(app: &tauri::AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let visible = win.is_visible().unwrap_or(false);
        let focused = win.is_focused().unwrap_or(false);
        if visible && focused {
            let _ = win.hide();
        } else {
            let _ = win.show();
            let _ = win.set_focus();
        }
    }
}

fn install_panic_logger() {
    let log_dir = dirs::data_local_dir()
        .map(|p| p.join("Raphael"))
        .unwrap_or_else(|| std::path::PathBuf::from("."));
    let _ = std::fs::create_dir_all(&log_dir);
    let log_path = log_dir.join("crash.log");
    std::panic::set_hook(Box::new(move |info| {
        let msg = format!(
            "[{}] PANIC: {}\n",
            chrono::Utc::now().to_rfc3339(),
            info
        );
        eprintln!("{msg}");
        if let Ok(mut f) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
        {
            use std::io::Write;
            let _ = f.write_all(msg.as_bytes());
        }
    }));
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    install_panic_logger();

    #[cfg(target_os = "macos")]
    let shortcut_mods = Modifiers::SUPER | Modifiers::SHIFT;
    #[cfg(not(target_os = "macos"))]
    let shortcut_mods = Modifiers::CONTROL | Modifiers::ALT;

    let toggle_shortcut = Shortcut::new(Some(shortcut_mods), Code::KeyR);

    let base_gs = tauri_plugin_global_shortcut::Builder::new().with_handler(
        move |app, sc, ev| {
            if sc == &toggle_shortcut && ev.state() == ShortcutState::Pressed {
                toggle_main_window(app);
            }
        },
    );
    let gs_builder = match base_gs.with_shortcuts([toggle_shortcut]) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("[raphael] shortcut register failed (continuing): {e}");
            tauri_plugin_global_shortcut::Builder::new()
        }
    };

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(gs_builder.build())
        .manage(DaemonState(std::sync::Arc::new(Mutex::new(None))))
        .setup(|app| {
            // 1. Sidecar 시작
            let handle = app.handle().clone();
            match spawn_daemon(&handle) {
                Ok(child) => {
                    let state: State<DaemonState> = app.state();
                    *state.0.lock().unwrap() = Some(child);
                    eprintln!("[raphael] daemon started on :8765");
                }
                Err(e) => eprintln!("[raphael] daemon spawn failed: {e}"),
            }

            // 2. Sidecar watchdog — 10초마다 health check, 죽었으면 재spawn
            {
                let handle2 = app.handle().clone();
                let state2: State<DaemonState> = app.state();
                let arc_clone = state2.0.clone();
                std::thread::spawn(move || {
                    loop {
                        std::thread::sleep(std::time::Duration::from_secs(10));
                        // Quick TCP check
                        let alive = std::net::TcpStream::connect_timeout(
                            &"127.0.0.1:8765".parse().unwrap(),
                            std::time::Duration::from_secs(2),
                        )
                        .is_ok();
                        if !alive {
                            eprintln!("[raphael] watchdog: sidecar unreachable, respawning...");
                            // Clear old child
                            { let _ = arc_clone.lock().unwrap().take(); }
                            match spawn_daemon(&handle2) {
                                Ok(child) => {
                                    *arc_clone.lock().unwrap() = Some(child);
                                    eprintln!("[raphael] watchdog: daemon restarted");
                                }
                                Err(e) => eprintln!("[raphael] watchdog: respawn failed: {e}"),
                            }
                        }
                    }
                });
            }

            // 3. Tray Icon (실패해도 앱은 계속)
            if let Err(e) = (|| -> tauri::Result<()> {
                let show_item =
                    MenuItem::with_id(app, "show", "Raphael 열기", true, None::<&str>)?;
                let hide_item = MenuItem::with_id(app, "hide", "숨기기", true, None::<&str>)?;
                let quit_item = MenuItem::with_id(app, "quit", "종료", true, None::<&str>)?;
                let menu = Menu::with_items(app, &[&show_item, &hide_item, &quit_item])?;
                let mut builder = TrayIconBuilder::with_id("main-tray")
                    .menu(&menu)
                    .show_menu_on_left_click(true)
                    .tooltip("Raphael")
                    .on_menu_event(|app, ev| match ev.id.as_ref() {
                        "show" => {
                            if let Some(w) = app.get_webview_window("main") {
                                let _ = w.show();
                                let _ = w.set_focus();
                            }
                        }
                        "hide" => {
                            if let Some(w) = app.get_webview_window("main") {
                                let _ = w.hide();
                            }
                        }
                        "quit" => app.exit(0),
                        _ => {}
                    });
                if let Some(icon) = app.default_window_icon() {
                    builder = builder.icon(icon.clone());
                }
                builder.build(app)?;
                Ok(())
            })() {
                eprintln!("[raphael] tray setup failed (continuing): {e}");
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![daemon_url, ensure_daemon])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            match event {
                RunEvent::ExitRequested { .. } => {
                    let state: State<DaemonState> = app.state();
                    let child_opt = state.0.lock().unwrap().take();
                    if let Some(child) = child_opt {
                        let _ = child.kill();
                        eprintln!("[raphael] daemon killed");
                    }
                }
                // watchdog thread handles sidecar respawn automatically
                _ => {}
            }
        });
}

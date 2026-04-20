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
fn ensure_daemon(app: tauri::AppHandle, _state: State<'_, DaemonState>) -> Result<String, String> {
    // spawn_daemon 내부에서 stale 여부까지 판별하므로 여기서는 항상 한 번 시도.
    // 이미 실행 중이고 최신이면 "already running" 으로 즉시 복귀.
    eprintln!("[raphael] ensure_daemon: checking daemon...");
    match spawn_daemon(&app) {
        Ok(_) => Ok("started".to_string()),
        Err(e) if e == "direct_spawn_ok" => Ok("started".to_string()),
        Err(e) if e == "already running" => Ok("already running".to_string()),
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

fn cleanup_pyinstaller_temp() {
    #[cfg(unix)]
    {
        use std::process::Command;
        // PyInstaller _MEI* 임시 디렉토리 정리 — 누적되면 새 추출이 극도로 느려짐
        if let Ok(output) = Command::new("sh")
            .args(["-c", "find /var/folders -maxdepth 5 -name '_MEI*' -type d -mmin +10 2>/dev/null"])
            .output()
        {
            let dirs = String::from_utf8_lossy(&output.stdout);
            let count = dirs.lines().filter(|l| !l.is_empty()).count();
            if count > 0 {
                let _ = Command::new("sh")
                    .args(["-c", "find /var/folders -maxdepth 5 -name '_MEI*' -type d -mmin +10 -exec rm -rf {} + 2>/dev/null"])
                    .output();
                eprintln!("[raphael] cleaned {count} stale _MEI* dirs");
            }
        }
    }
}

fn remove_quarantine() {
    #[cfg(target_os = "macos")]
    {
        use std::process::Command;
        if let Ok(exe) = std::env::current_exe() {
            if let Some(macos_dir) = exe.parent() {
                let raphaeld = macos_dir.join("raphaeld");
                if raphaeld.exists() {
                    let _ = Command::new("xattr")
                        .args(["-dr", "com.apple.quarantine"])
                        .arg(&raphaeld)
                        .output();
                    eprintln!("[raphael] quarantine removed from {}", raphaeld.display());
                }
                // Also remove from app bundle
                if let Some(contents) = macos_dir.parent() {
                    if let Some(app_dir) = contents.parent() {
                        let _ = Command::new("xattr")
                            .args(["-dr", "com.apple.quarantine"])
                            .arg(app_dir)
                            .output();
                    }
                }
            }
        }
    }
}

/// 실행 중인 데몬이 현재 소스 코드와 같은 버전인지 확인.
/// 오래된(stale) 버전이면 해당 PID 를 반환해 호출측이 kill 하도록 한다.
/// 최신(또는 판별 불가)이면 None 반환.
fn detect_stale_daemon(project_dir: &std::path::Path) -> Option<u32> {
    // 데몬이 import 하는 주요 디렉토리 전체를 훑어 최신 mtime 을 계산한다.
    // (daemon.py 하나만 보면 core/tool_runner.py 같은 의존 모듈 변경을 놓친다)
    fn latest_mtime(root: &std::path::Path) -> i64 {
        let mut latest: i64 = 0;
        let mut stack: Vec<std::path::PathBuf> = vec![root.to_path_buf()];
        while let Some(dir) = stack.pop() {
            let entries = match std::fs::read_dir(&dir) {
                Ok(e) => e,
                Err(_) => continue,
            };
            for entry in entries.flatten() {
                let path = entry.path();
                let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
                if name == "__pycache__" || name.starts_with('.') {
                    continue;
                }
                if let Ok(ft) = entry.file_type() {
                    if ft.is_dir() {
                        stack.push(path);
                    } else if ft.is_file()
                        && path.extension().and_then(|e| e.to_str()) == Some("py")
                    {
                        if let Ok(md) = entry.metadata() {
                            if let Ok(t) = md.modified() {
                                if let Ok(d) = t.duration_since(std::time::UNIX_EPOCH) {
                                    let secs = d.as_secs() as i64;
                                    if secs > latest {
                                        latest = secs;
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        latest
    }

    let mut expected_mtime: i64 = 0;
    for sub in ["interfaces", "core", "tools", "config"] {
        let d = project_dir.join(sub);
        if d.is_dir() {
            let m = latest_mtime(&d);
            if m > expected_mtime {
                expected_mtime = m;
            }
        }
    }
    if expected_mtime == 0 {
        return None;
    }

    // 간단한 HTTP/1.1 GET — 외부 크레이트 없이 처리.
    use std::io::{Read, Write};
    let mut stream = match std::net::TcpStream::connect_timeout(
        &"127.0.0.1:8765".parse().unwrap(),
        std::time::Duration::from_secs(1),
    ) {
        Ok(s) => s,
        Err(_) => return None,
    };
    let _ = stream.set_read_timeout(Some(std::time::Duration::from_secs(2)));
    let req = b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
    if stream.write_all(req).is_err() {
        return None;
    }
    let mut buf = Vec::with_capacity(512);
    let _ = stream.read_to_end(&mut buf);
    let text = String::from_utf8_lossy(&buf);
    let body = match text.split_once("\r\n\r\n") {
        Some((_, b)) => b.trim_start(),
        None => return None,
    };
    // chunked encoding이면 첫 chunk 사이즈 라인 스킵 (FastAPI 기본은 Content-Length 라 보통 아님)
    let json_body = if let Some(first_line_end) = body.find('\n') {
        let first = &body[..first_line_end].trim();
        if first.chars().all(|c| c.is_ascii_hexdigit()) && !first.is_empty() {
            &body[first_line_end + 1..]
        } else {
            body
        }
    } else {
        body
    };

    let v: serde_json::Value = match serde_json::from_str(json_body) {
        Ok(x) => x,
        Err(_) => return None,
    };
    let running_mtime = v.get("source_mtime").and_then(|x| x.as_i64()).unwrap_or(0);
    let pid = v.get("pid").and_then(|x| x.as_u64()).unwrap_or(0) as u32;

    // 1초 허용 — 동일 코드라도 os mtime 해상도 차이 흡수
    if running_mtime + 1 < expected_mtime {
        eprintln!(
            "[raphael] stale daemon detected: running mtime={} expected={} (PID {})",
            running_mtime, expected_mtime, pid
        );
        if pid > 0 {
            return Some(pid);
        }
    }
    None
}

fn spawn_daemon(_app: &tauri::AppHandle) -> Result<CommandChild, String> {
    // Raphael 프로젝트 디렉토리 (dev 환경에서만 존재)
    let home = dirs::home_dir().unwrap_or_else(|| std::path::PathBuf::from("/Users"))
        .to_string_lossy().to_string();
    let project_dir = format!("{home}/Raphael");
    let project_path = std::path::Path::new(&project_dir);

    // 이미 실행 중이면 — 단, stale 코드면 kill 하고 재spawn.
    if std::net::TcpStream::connect_timeout(
        &"127.0.0.1:8765".parse().unwrap(),
        std::time::Duration::from_secs(1),
    ).is_ok() {
        if let Some(stale_pid) = detect_stale_daemon(project_path) {
            use std::process::Command;
            eprintln!("[raphael] killing stale daemon PID {}", stale_pid);
            let _ = Command::new("kill").arg(stale_pid.to_string()).output();
            std::thread::sleep(std::time::Duration::from_secs(1));
            // 같은 포트 점유가 남아있을 수 있어 한 번 더 포트 청소
            kill_stale_daemon();
        } else {
            return Err("already running".to_string());
        }
    } else {
        kill_stale_daemon();
    }

    // 방법 1 (우선): Python uvicorn 직접 실행 — PyInstaller 추출 없이 즉시 시작
    eprintln!("[raphael] HOME={home}");

    let python_paths = [
        // Raphael venv (절대 경로)
        format!("{home}/Raphael/.venv/bin/python3"),
        // Homebrew
        "/opt/homebrew/bin/python3".to_string(),
        "/usr/local/bin/python3".to_string(),
        "/usr/bin/python3".to_string(),
    ];

    for py_str in &python_paths {
        let py = std::path::Path::new(py_str);
        if !py.exists() {
            eprintln!("[raphael] skip (not found): {py_str}");
            continue;
        }
        if !project_path.join("interfaces/daemon.py").exists() {
            eprintln!("[raphael] skip: {project_dir}/interfaces/daemon.py not found");
            break;
        }
        eprintln!("[raphael] trying: {py_str} -m uvicorn (cwd={project_dir})");
        match std::process::Command::new(py)
            .args(["-m", "uvicorn", "interfaces.daemon:app",
                   "--host", "127.0.0.1", "--port", "8765"])
            .current_dir(project_path)
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
        {
            Ok(child) => {
                eprintln!("[raphael] Python daemon spawned (PID {})", child.id());
                return Err("direct_spawn_ok".to_string());
            }
            Err(e) => {
                eprintln!("[raphael] Python spawn failed ({}): {e}", py.display());
            }
        }
    }

    // 방법 2 (fallback): PyInstaller sidecar
    cleanup_pyinstaller_temp();
    remove_quarantine();

    let raphaeld_path = std::env::current_exe()
        .map_err(|e| format!("exe path: {e}"))?
        .parent()
        .ok_or("no parent dir")?
        .join("raphaeld");

    if raphaeld_path.exists() {
        eprintln!("[raphael] fallback: PyInstaller {}", raphaeld_path.display());
        match std::process::Command::new(&raphaeld_path)
            .args(["--host", "127.0.0.1", "--port", "8765"])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
        {
            Ok(child) => {
                eprintln!("[raphael] PyInstaller daemon spawned (PID {})", child.id());
                return Err("direct_spawn_ok".to_string());
            }
            Err(e) => eprintln!("[raphael] PyInstaller spawn failed: {e}"),
        }
    }

    Err("all spawn methods failed".to_string())
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
                Err(e) => {
                    if e == "direct_spawn_ok" {
                        eprintln!("[raphael] daemon started via direct exec");
                    } else {
                        eprintln!("[raphael] daemon spawn failed: {e}");
                    }
                }
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

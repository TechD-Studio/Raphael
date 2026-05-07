use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{Manager, RunEvent, State};
use tauri_plugin_global_shortcut::{Code, Modifiers, Shortcut, ShortcutState};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct DaemonState(std::sync::Arc<Mutex<Option<CommandChild>>>);

// 업데이트 진행 중에는 watchdog 의 sidecar 재spawn 을 막아야 한다.
// 새 .app 교체 도중 PyInstaller onefile 바이너리가 다시 mmap 되면 macOS Sequoia
// 에서 atomic replace 가 silent 로 실패해 v0.1.45 → v0.1.46 업데이트가
// 적용되지 않는 사례가 발생.
static UPDATE_IN_PROGRESS: AtomicBool = AtomicBool::new(false);

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

/// 자동 업데이트 직전에 호출.
/// 1) UPDATE_IN_PROGRESS 플래그를 켜서 watchdog 의 sidecar 재spawn 을 정지.
/// 2) 관리 중인 sidecar child 를 명시적으로 kill.
/// 3) :8765 점유 + raphaeld 잔존 프로세스까지 정리.
/// 4) 파일 핸들 해제를 위해 짧게 sleep.
#[tauri::command]
fn prepare_for_update(state: State<'_, DaemonState>) -> Result<(), String> {
    eprintln!("[raphael] prepare_for_update: suspending watchdog + killing daemon");
    UPDATE_IN_PROGRESS.store(true, Ordering::SeqCst);
    let child_opt = state.0.lock().unwrap().take();
    if let Some(child) = child_opt {
        let _ = child.kill();
    }
    kill_stale_daemon();
    std::thread::sleep(std::time::Duration::from_millis(800));
    Ok(())
}

/// 업데이트가 실패/취소된 경우 watchdog 를 재개.
#[tauri::command]
fn cancel_update() -> Result<(), String> {
    eprintln!("[raphael] cancel_update: resuming watchdog");
    UPDATE_IN_PROGRESS.store(false, Ordering::SeqCst);
    Ok(())
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

fn remove_quarantine(raphaeld_dir: &std::path::Path) {
    #[cfg(target_os = "macos")]
    {
        use std::process::Command;
        if raphaeld_dir.exists() {
            // 폴더 전체에서 재귀 제거 — _internal/ 안의 .so 파일들도 모두 quarantine 풀어야
            // PyInstaller onedir 부트로더가 import 가능.
            let _ = Command::new("xattr")
                .args(["-dr", "com.apple.quarantine"])
                .arg(raphaeld_dir)
                .output();
            eprintln!("[raphael] quarantine removed from {}", raphaeld_dir.display());
        }
        if let Ok(exe) = std::env::current_exe() {
            if let Some(macos_dir) = exe.parent() {
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
    #[cfg(not(target_os = "macos"))]
    let _ = raphaeld_dir;
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
    let running_host = v.get("bind_host").and_then(|x| x.as_str()).unwrap_or("");

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

    // bind host 변경 감지 — auto_web 토글 후 재시작 자동화
    let desired_host = if read_auto_web() { "0.0.0.0" } else { "127.0.0.1" };
    if !running_host.is_empty() && running_host != desired_host {
        eprintln!(
            "[raphael] bind host changed: running={} desired={} (PID {})",
            running_host, desired_host, pid
        );
        if pid > 0 {
            return Some(pid);
        }
    }
    None
}

/// `~/.raphael/config/desktop.json`의 `auto_web` 플래그를 읽어 true면
/// 데몬을 0.0.0.0에 바인딩(LAN 전체 접속 허용), false면 127.0.0.1에만 바인딩한다.
/// 파일 없거나 파싱 실패면 false 취급.
fn read_auto_web() -> bool {
    let home = match dirs::home_dir() {
        Some(h) => h,
        None => return false,
    };
    let path = home.join(".raphael").join("config").join("desktop.json");
    let content = match std::fs::read_to_string(&path) {
        Ok(c) => c,
        Err(_) => return false,
    };
    let v: serde_json::Value = match serde_json::from_str(&content) {
        Ok(v) => v,
        Err(_) => return false,
    };
    v.get("auto_web").and_then(|x| x.as_bool()).unwrap_or(false)
}

/// macOS GUI 앱은 `/usr/bin:/bin:/usr/sbin:/sbin` 만 상속하므로 user-local 설치된
/// `claude`, `node`, `ollama` 등을 데몬 서브프로세스가 못 찾는다.
/// 흔한 설치 경로를 PATH 앞에 덧붙인 값을 반환한다.
fn extended_path() -> String {
    let home = dirs::home_dir().unwrap_or_else(|| std::path::PathBuf::from("/Users"))
        .to_string_lossy().to_string();
    let extras = [
        format!("{home}/.local/bin"),
        format!("{home}/.npm-global/bin"),
        format!("{home}/bin"),
        "/opt/homebrew/bin".to_string(),
        "/opt/homebrew/sbin".to_string(),
        "/usr/local/bin".to_string(),
        "/usr/local/sbin".to_string(),
    ];
    let existing = std::env::var("PATH").unwrap_or_default();
    let existing_set: std::collections::HashSet<&str> = existing.split(':').collect();
    let mut parts: Vec<String> = extras.into_iter()
        .filter(|p| !existing_set.contains(p.as_str()))
        .collect();
    if !existing.is_empty() {
        parts.push(existing);
    }
    parts.join(":")
}

fn spawn_daemon(app: &tauri::AppHandle) -> Result<CommandChild, String> {
    // Raphael 프로젝트 디렉토리 (dev 환경에서만 존재)
    let home = dirs::home_dir().unwrap_or_else(|| std::path::PathBuf::from("/Users"))
        .to_string_lossy().to_string();
    let project_dir = format!("{home}/Raphael");
    let project_path = std::path::Path::new(&project_dir);

    // GUI 앱 상속 PATH가 비어있어 claude/node/ollama 등 user-local 바이너리를
    // 데몬이 못 찾는 문제 방지
    let ext_path = extended_path();
    eprintln!("[raphael] extended PATH: {ext_path}");

    // auto_web 플래그: 켜져있으면 0.0.0.0에 바인딩하여 LAN에서도 접근 가능
    let bind_host = if read_auto_web() { "0.0.0.0" } else { "127.0.0.1" };
    eprintln!("[raphael] bind host: {bind_host} (auto_web={})", read_auto_web());

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
                   "--host", bind_host, "--port", "8765"])
            .current_dir(project_path)
            .env("PATH", &ext_path)
            .env("RAPHAEL_BIND_HOST", bind_host)
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

    // 방법 2 (fallback): PyInstaller --onedir sidecar
    // bundle.resources 가 binaries/raphaeld/ 를 .app/Contents/Resources/raphaeld/ 로 복사한다.
    // --onefile 시절의 _MEI 임시 디렉토리 정리는 더 이상 불필요(onedir 은 추출 없음)이지만
    // 과거 설치본 잔존 가능성 때문에 한 번 호출해 둔다.
    cleanup_pyinstaller_temp();

    use tauri::Manager;
    let resource_dir = match app.path().resource_dir() {
        Ok(d) => d,
        Err(e) => {
            eprintln!("[raphael] resource_dir() failed: {e}");
            return Err(format!("resource_dir: {e}"));
        }
    };
    let raphaeld_dir = resource_dir.join("raphaeld");
    let raphaeld_bin = if cfg!(windows) {
        raphaeld_dir.join("raphaeld.exe")
    } else {
        raphaeld_dir.join("raphaeld")
    };

    remove_quarantine(&raphaeld_dir);

    if raphaeld_bin.exists() {
        eprintln!("[raphael] fallback: PyInstaller onedir {}", raphaeld_bin.display());
        match std::process::Command::new(&raphaeld_bin)
            .args(["--host", bind_host, "--port", "8765"])
            .env("PATH", &ext_path)
            .env("RAPHAEL_BIND_HOST", bind_host)
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
    } else {
        eprintln!("[raphael] raphaeld binary not found at {}", raphaeld_bin.display());
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
                        // 업데이트 중이면 sidecar 가 죽어있어도 절대 재spawn 하지 않는다.
                        // 새 .app 교체가 끝나고 relaunch 될 때까지 손대지 않는다.
                        if UPDATE_IN_PROGRESS.load(Ordering::SeqCst) {
                            continue;
                        }
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
        .invoke_handler(tauri::generate_handler![
            daemon_url,
            ensure_daemon,
            prepare_for_update,
            cancel_update
        ])
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

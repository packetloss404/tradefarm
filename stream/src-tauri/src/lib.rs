// TradeFarm Stream — Tauri shell.
//
// Minimal: hosts the Vite-built React app, exposes the FS plugin so the
// frontend can persist stream-settings.json under appDataDir.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_fs::init())
        .setup(|_app| Ok(()))
        .run(tauri::generate_context!())
        .expect("error while running TradeFarm Stream");
}

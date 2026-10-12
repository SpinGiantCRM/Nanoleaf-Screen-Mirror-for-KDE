use std::process::Command;

fn main() {
    let rustc = std::env::var_os("RUSTC").expect("Cargo supplies its Rust compiler");
    let version = Command::new(rustc)
        .arg("--version")
        .output()
        .expect("Rust compiler version must be available");
    assert!(version.status.success());
    let version = String::from_utf8(version.stdout).expect("compiler version is UTF-8");
    println!(
        "cargo:rustc-env=NANOLEAF_CORE_BUILD_RUSTC={}",
        version.trim()
    );
}

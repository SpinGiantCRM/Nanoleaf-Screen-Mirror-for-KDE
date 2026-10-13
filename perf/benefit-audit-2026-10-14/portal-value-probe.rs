use zbus::zvariant::{OwnedValue, Value};
fn main() {
    let id = OwnedValue::try_from(Value::from("screen-id")).unwrap();
    let parsed: Result<u32, _> = id.try_into();
    println!("spec string id -> current u32 parser: {:?}", parsed);
    let serial = OwnedValue::from(123456u64);
    let parsed: Result<String, _> = serial.try_into();
    println!("spec u64 serial -> current String parser: {:?}", parsed);
}

use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fmt::Write;

// v0.5 の署名済み snapshot は Python json.dumps(sort_keys=True) のバイト列を使う。
pub fn hash(v: &Value) -> String {
    let mut output = String::new();
    write_value(v, &mut output);
    sha256(&output)
}
pub fn sha256(s: &str) -> String {
    format!("{:x}", Sha256::digest(s.as_bytes()))
}
fn string(s: &str, out: &mut String) {
    let escaped = serde_json::to_string(s).expect("文字列の JSON 化");
    for c in escaped.chars() {
        if c < '\u{7f}' {
            out.push(c)
        } else {
            for unit in c.encode_utf16(&mut [0; 2]) {
                write!(out, "\\u{unit:04x}").unwrap()
            }
        }
    }
}
fn write_value(v: &Value, out: &mut String) {
    match v {
        Value::Object(m) => {
            out.push('{');
            let mut fields = m.iter().collect::<Vec<_>>();
            fields.sort_by_key(|(k, _)| *k);
            for (i, (k, v)) in fields.into_iter().enumerate() {
                if i > 0 {
                    out.push_str(", ")
                }
                string(k, out);
                out.push_str(": ");
                write_value(v, out)
            }
            out.push('}')
        }
        Value::Array(a) => {
            out.push('[');
            for (i, v) in a.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ")
                }
                write_value(v, out)
            }
            out.push(']')
        }
        Value::String(s) => string(s, out),
        Value::Number(n) if n.is_f64() => {
            let f = n.as_f64().unwrap();
            let short = format!("{f:?}");
            if let Some((m, e)) = short.split_once('e') {
                write!(out, "{m}e{:+03}", e.parse::<i32>().unwrap()).unwrap()
            } else {
                out.push_str(&short)
            }
        }
        _ => out.push_str(&v.to_string()),
    }
}

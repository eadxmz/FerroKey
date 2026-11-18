use jni::objects::{
    GlobalRef, JClass, JFieldID, JMethodID, JObject, JStaticMethodID, JString, JValue, JValueOwned,
};
use jni::signature::{Primitive, ReturnType};
use jni::JNIEnv;
use std::sync::OnceLock;

const ID_SELECT_ALL: i32 = 0x0102001f; // android.R.id.selectAll
const ID_CUT: i32 = 0x01020020;        // android.R.id.cut
const ID_COPY: i32 = 0x01020021;       // android.R.id.copy
const ID_PASTE: i32 = 0x01020022;      // android.R.id.paste
const ID_UNDO: i32 = 0x01020032;       // android.R.id.undo
const ID_REDO: i32 = 0x01020033;       // android.R.id.redo

struct InputJniCache {
    ic_commit_text: JMethodID,
    ic_delete_surrounding: JMethodID,
    ic_get_text_before: JMethodID,
    ic_send_key_event: JMethodID,
    ic_perform_context: JMethodID,
    ic_perform_editor: JMethodID,
    cs_length: JMethodID,
    cs_to_string: JMethodID,
    key_event_class: GlobalRef,
    key_event_ctor_simple: JMethodID,
    key_event_ctor_full: JMethodID,
    sysclock_class: GlobalRef,
    sysclock_uptime: JStaticMethodID,
    editor_ime_options: JFieldID,
}

static INPUT_CACHE: OnceLock<InputJniCache> = OnceLock::new();

fn cache<'a>(env: &mut JNIEnv<'a>) -> &'a InputJniCache {
    INPUT_CACHE.get_or_init(|| {
        let ke_cls = env.find_class("android/view/KeyEvent").unwrap();
        let key_event_class = env.new_global_ref(&ke_cls).unwrap();
        let _ = env.delete_local_ref(ke_cls);

        let sc_cls = env.find_class("android/os/SystemClock").unwrap();
        let sysclock_class = env.new_global_ref(&sc_cls).unwrap();
        let _ = env.delete_local_ref(sc_cls);

        InputJniCache {
            ic_commit_text: env
                .get_method_id(
                    "android/view/inputmethod/InputConnection",
                    "commitText",
                    "(Ljava/lang/CharSequence;I)Z",
                )
                .unwrap(),
            ic_delete_surrounding: env
                .get_method_id(
                    "android/view/inputmethod/InputConnection",
                    "deleteSurroundingText",
                    "(II)Z",
                )
                .unwrap(),
            ic_get_text_before: env
                .get_method_id(
                    "android/view/inputmethod/InputConnection",
                    "getTextBeforeCursor",
                    "(II)Ljava/lang/CharSequence;",
                )
                .unwrap(),
            ic_send_key_event: env
                .get_method_id(
                    "android/view/inputmethod/InputConnection",
                    "sendKeyEvent",
                    "(Landroid/view/KeyEvent;)Z",
                )
                .unwrap(),
            ic_perform_context: env
                .get_method_id(
                    "android/view/inputmethod/InputConnection",
                    "performContextMenuAction",
                    "(I)Z",
                )
                .unwrap(),
            ic_perform_editor: env
                .get_method_id(
                    "android/view/inputmethod/InputConnection",
                    "performEditorAction",
                    "(I)Z",
                )
                .unwrap(),
            cs_length: env
                .get_method_id("java/lang/CharSequence", "length", "()I")
                .unwrap(),
            cs_to_string: env
                .get_method_id("java/lang/CharSequence", "toString", "()Ljava/lang/String;")
                .unwrap(),
            key_event_class,
            key_event_ctor_simple: env
                .get_method_id("android/view/KeyEvent", "<init>", "(II)V")
                .unwrap(),
            key_event_ctor_full: env
                .get_method_id("android/view/KeyEvent", "<init>", "(JJIIIIIIII)V")
                .unwrap(),
            sysclock_class,
            sysclock_uptime: env
                .get_static_method_id("android/os/SystemClock", "uptimeMillis", "()J")
                .unwrap(),
            editor_ime_options: env
                .get_field_id("android/view/inputmethod/EditorInfo", "imeOptions", "I")
                .unwrap(),
        }
    })
}

pub fn commit_text(env: &mut JNIEnv, ic: &JObject, text: &str) {
    if ic.is_null() {
        return;
    }
    let c = cache(env);
    if let Ok(jstr) = env.new_string(text) {
        let _ = unsafe {
            env.call_method_unchecked(
                ic,
                c.ic_commit_text,
                ReturnType::Primitive(Primitive::Boolean),
                &[JValue::Object(&jstr).as_jni(), JValue::Int(1).as_jni()],
            )
        };
        let _ = env.delete_local_ref(jstr);
    }
    let _ = env.exception_clear();
}

pub fn delete_surrounding_text(env: &mut JNIEnv, ic: &JObject, before: i32, after: i32) {
    if ic.is_null() {
        return;
    }
    let c = cache(env);
    let _ = unsafe {
        env.call_method_unchecked(
            ic,
            c.ic_delete_surrounding,
            ReturnType::Primitive(Primitive::Boolean),
            &[JValue::Int(before).as_jni(), JValue::Int(after).as_jni()],
        )
    };
    let _ = env.exception_clear();
}

pub fn is_field_empty(env: &mut JNIEnv, ic: &JObject) -> bool {
    if ic.is_null() {
        return true;
    }
    let c = cache(env);
    let res = unsafe {
        env.call_method_unchecked(
            ic,
            c.ic_get_text_before,
            ReturnType::Object,
            &[JValue::Int(1).as_jni(), JValue::Int(0).as_jni()],
        )
    };
    if let Ok(JValueOwned::Object(cs)) = res {
        if cs.is_null() {
            return true;
        }
        let len = unsafe {
            env.call_method_unchecked(&cs, c.cs_length, ReturnType::Primitive(Primitive::Int), &[])
        }
        .and_then(|v| v.i())
        .unwrap_or(0);
        let _ = env.delete_local_ref(cs);
        return len == 0;
    }
    let _ = env.exception_clear();
    false
}

pub fn should_auto_cap(env: &mut JNIEnv, ic: &JObject) -> bool {
    if ic.is_null() {
        return true;
    }
    let c = cache(env);
    let res = unsafe {
        env.call_method_unchecked(
            ic,
            c.ic_get_text_before,
            ReturnType::Object,
            &[JValue::Int(3).as_jni(), JValue::Int(0).as_jni()],
        )
    };
    if let Ok(JValueOwned::Object(cs)) = res {
        if cs.is_null() {
            return true;
        }
        let mut should_cap = false;
        let to_str = unsafe {
            env.call_method_unchecked(&cs, c.cs_to_string, ReturnType::Object, &[])
        };
        if let Ok(JValueOwned::Object(jstr_obj)) = to_str {
            if !jstr_obj.is_null() {
                let jstr = JString::from(jstr_obj);
                if let Ok(rust_str) = env.get_string(&jstr) {
                    let s = rust_str.to_string_lossy();
                    if s.is_empty()
                        || s.ends_with(". ")
                        || s.ends_with("! ")
                        || s.ends_with("? ")
                        || s.ends_with('\n')
                    {
                        should_cap = true;
                    }
                }
                let _ = env.delete_local_ref(jstr);
            }
        }
        let _ = env.delete_local_ref(cs);
        return should_cap;
    }
    let _ = env.exception_clear();
    true
}

pub fn send_simple_key(env: &mut JNIEnv, ic: &JObject, key_code: i32) {
    if ic.is_null() {
        return;
    }
    let c = cache(env);
    let ke_cls = unsafe { JClass::from_raw(c.key_event_class.as_raw()) };
    for action in [0i32, 1i32] {
        let ev = unsafe {
            env.new_object_unchecked(
                &ke_cls,
                c.key_event_ctor_simple,
                &[JValue::Int(action).as_jni(), JValue::Int(key_code).as_jni()],
            )
        };
        if let Ok(ev) = ev {
            let _ = unsafe {
                env.call_method_unchecked(
                    ic,
                    c.ic_send_key_event,
                    ReturnType::Primitive(Primitive::Boolean),
                    &[JValue::Object(&ev).as_jni()],
                )
            };
            let _ = env.delete_local_ref(ev);
        }
    }
    let _ = env.exception_clear();
}

pub fn send_ctrl_key_event(env: &mut JNIEnv, ic: &JObject, key_code: i32) {
    if ic.is_null() {
        return;
    }
    let c = cache(env);
    let sc_cls = unsafe { JClass::from_raw(c.sysclock_class.as_raw()) };
    let now = unsafe {
        env.call_static_method_unchecked(
            &sc_cls,
            c.sysclock_uptime,
            ReturnType::Primitive(Primitive::Long),
            &[],
        )
    }
    .and_then(|v| v.j())
    .unwrap_or(0);

    let meta: i32 = 0x1000 | 0x2000; // META_CTRL_ON | META_CTRL_LEFT_ON
    let device_id: i32 = -1;         // KeyCharacterMap.VIRTUAL_KEYBOARD
    let flags: i32 = 0x2 | 0x4;      // FLAG_SOFT_KEYBOARD | FLAG_KEEP_TOUCH_MODE
    let source: i32 = 0x00000101;    // InputDevice.SOURCE_KEYBOARD

    let ke_cls = unsafe { JClass::from_raw(c.key_event_class.as_raw()) };
    for (action, ts) in [(0i32, now), (1i32, now + 10)] {
        let ev = unsafe {
            env.new_object_unchecked(
                &ke_cls,
                c.key_event_ctor_full,
                &[
                    JValue::Long(now).as_jni(),
                    JValue::Long(ts).as_jni(),
                    JValue::Int(action).as_jni(),
                    JValue::Int(key_code).as_jni(),
                    JValue::Int(0).as_jni(),
                    JValue::Int(meta).as_jni(),
                    JValue::Int(device_id).as_jni(),
                    JValue::Int(0).as_jni(),
                    JValue::Int(flags).as_jni(),
                    JValue::Int(source).as_jni(),
                ],
            )
        };
        if let Ok(ev) = ev {
            let _ = unsafe {
                env.call_method_unchecked(
                    ic,
                    c.ic_send_key_event,
                    ReturnType::Primitive(Primitive::Boolean),
                    &[JValue::Object(&ev).as_jni()],
                )
            };
            let _ = env.delete_local_ref(ev);
        }
    }
    let _ = env.exception_clear();
}

fn perform_context_action(env: &mut JNIEnv, ic: &JObject, action_id: i32) -> bool {
    if ic.is_null() {
        return false;
    }
    let c = cache(env);
    let res = unsafe {
        env.call_method_unchecked(
            ic,
            c.ic_perform_context,
            ReturnType::Primitive(Primitive::Boolean),
            &[JValue::Int(action_id).as_jni()],
        )
    };
    match res {
        Ok(v) => v.z().unwrap_or(false),
        Err(_) => {
            let _ = env.exception_clear();
            false
        }
    }
}

pub fn execute_ctrl_shortcut(env: &mut JNIEnv, ic: &JObject, key: &str) {
    match key {
        "A" => {
            if !perform_context_action(env, ic, ID_SELECT_ALL) {
                send_ctrl_key_event(env, ic, 29); // KEYCODE_A
            }
        }
        "Z" => {
            if !perform_context_action(env, ic, ID_UNDO) {
                send_ctrl_key_event(env, ic, 54); // KEYCODE_Z
            }
        }
        "Y" => {
            if !perform_context_action(env, ic, ID_REDO) {
                send_ctrl_key_event(env, ic, 53); // KEYCODE_Y
            }
        }
        "X" => {
            if !perform_context_action(env, ic, ID_CUT) {
                send_ctrl_key_event(env, ic, 52); // KEYCODE_X
            }
        }
        "C" => {
            if !perform_context_action(env, ic, ID_COPY) {
                send_ctrl_key_event(env, ic, 31); // KEYCODE_C
            }
        }
        "V" => {
            if !perform_context_action(env, ic, ID_PASTE) {
                send_ctrl_key_event(env, ic, 50); // KEYCODE_V
            }
        }
        "BKSP" => {
            send_ctrl_key_event(env, ic, 67); // KEYCODE_DEL
        }
        _ => {
            if let Some(ch) = key.chars().next() {
                if ch.is_ascii_uppercase() {
                    let code = 29 + (ch as i32 - 'A' as i32);
                    send_ctrl_key_event(env, ic, code);
                }
            }
        }
    }
}

pub fn perform_submit(env: &mut JNIEnv, ic: &JObject, editor_info: &JObject) {
    if ic.is_null() {
        return;
    }
    let c = cache(env);
    let mut action_id: i32 = 0;
    if !editor_info.is_null() {
        let v = unsafe {
            env.get_field_unchecked(
                editor_info,
                c.editor_ime_options,
                ReturnType::Primitive(Primitive::Int),
            )
        };
        if let Ok(v) = v {
            action_id = v.i().unwrap_or(0) & 0x000000FF;
        }
    }
    if action_id != 0 && action_id != 1 {
        let _ = unsafe {
            env.call_method_unchecked(
                ic,
                c.ic_perform_editor,
                ReturnType::Primitive(Primitive::Boolean),
                &[JValue::Int(action_id).as_jni()],
            )
        };
    } else {
        let _ = unsafe {
            env.call_method_unchecked(
                ic,
                c.ic_perform_editor,
                ReturnType::Primitive(Primitive::Boolean),
                &[JValue::Int(3).as_jni()],
            )
        };
        send_simple_key(env, ic, 66);
    }
    let _ = env.exception_clear();
}

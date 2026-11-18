import os

FILES = {
    ".gitignore": r"""/target
/build
/jniLibs
*.apk
*.idsig
*.keystore
""",

    ".gitattributes": r"""setup_ferrokey.py linguist-vendored
java/** linguist-vendored
""",

    "Cargo.toml": r"""[package]
name = "ferrokey"
version = "0.7.0"
edition = "2021"

[lib]
crate-type = ["cdylib"]

[dependencies]
jni = "0.21"

[profile.release]
opt-level = "z"
lto = true
codegen-units = 1
strip = true
panic = "abort"
""",

    "src/lib.rs": r"""mod input;
mod renderer;
mod state;

use jni::objects::{JClass, JObject};
use jni::sys::jint;
use jni::JNIEnv;
use state::{Action, STATE};

#[no_mangle]
pub extern "system" fn Java_com_ferrostb_keyboard_FerroKeyboardService_nativeSyncAutoCap(
    mut env: JNIEnv,
    _class: JClass,
    ic: JObject,
) {
    let should_cap = input::should_auto_cap(&mut env, &ic);
    let mut st = STATE.lock().unwrap();
    st.set_auto_cap(should_cap);
}

/// Returns:
/// 0 = Pass event through to Android
/// 1 = Consumed + Redraw keyboard view
/// 2 = Consumed + Explicitly hide keyboard window
#[no_mangle]
pub extern "system" fn Java_com_ferrostb_keyboard_FerroKeyboardService_nativeOnKey(
    mut env: JNIEnv,
    _class: JClass,
    ic: JObject,
    editor_info: JObject,
    key_code: jint,
) -> jint {
    let action = {
        let mut st = STATE.lock().unwrap();
        st.on_key(key_code)
    };

    match action {
        Action::Pass => 0,
        Action::Redraw => 1,
        Action::Hide => 2,
        Action::Commit(text) => {
            input::commit_text(&mut env, &ic, &text);
            1
        }
        Action::Backspace => {
            input::delete_surrounding_text(&mut env, &ic, 1, 0);
            if input::is_field_empty(&mut env, &ic) {
                let mut st = STATE.lock().unwrap();
                st.set_auto_cap(true);
            }
            1
        }
        Action::CursorLeft => {
            input::send_simple_key(&mut env, &ic, 21); // KEYCODE_DPAD_LEFT
            1
        }
        Action::CursorRight => {
            input::send_simple_key(&mut env, &ic, 22); // KEYCODE_DPAD_RIGHT
            1
        }
        Action::Ctrl(key) => {
            input::execute_ctrl_shortcut(&mut env, &ic, &key);
            if key == "X" && input::is_field_empty(&mut env, &ic) {
                let mut st = STATE.lock().unwrap();
                st.set_auto_cap(true);
            }
            1
        }
        Action::Submit => {
            input::perform_submit(&mut env, &ic, &editor_info);
            2
        }
    }
}

#[no_mangle]
pub extern "system" fn Java_com_ferrostb_keyboard_FerroKeyboardService_nativeOnDraw(
    mut env: JNIEnv,
    _class: JClass,
    canvas: JObject,
    fill_paint: JObject,
    stroke_paint: JObject,
    path: JObject,
    width: jint,
    height: jint,
) {
    let snapshot = {
        let st = STATE.lock().unwrap();
        st.snapshot()
    };
    renderer::draw_keyboard(
        &mut env,
        &canvas,
        &fill_paint,
        &stroke_paint,
        &path,
        width as f32,
        height as f32,
        &snapshot,
    );
}
""",

    "src/state.rs": r"""use std::sync::Mutex;

pub const KEYCODE_BACK: i32 = 4;
pub const KEYCODE_DPAD_UP: i32 = 19;
pub const KEYCODE_DPAD_DOWN: i32 = 20;
pub const KEYCODE_DPAD_LEFT: i32 = 21;
pub const KEYCODE_DPAD_RIGHT: i32 = 22;
pub const KEYCODE_DPAD_CENTER: i32 = 23;
pub const KEYCODE_ENTER: i32 = 66;
pub const KEYCODE_DEL: i32 = 67;
pub const KEYCODE_NUMPAD_ENTER: i32 = 160;

#[derive(Clone, Copy, PartialEq)]
pub enum Layer {
    Lower = 0,
    Shift = 1,
    CapsLock = 2,
    Numbers = 3,
    Symbols = 4,
}

#[derive(Clone, Copy, PartialEq)]
pub enum CtrlMode {
    Off = 0,
    OneShot = 1,
    Locked = 2,
}

pub enum Action {
    Pass,
    Redraw,
    Hide,
    Commit(String),
    Backspace,
    CursorLeft,
    CursorRight,
    Ctrl(String),
    Submit,
}

#[derive(Clone)]
pub struct GridSnapshot {
    pub focus_row: usize,
    pub focus_col: usize,
    pub layer: Layer,
    pub ctrl: CtrlMode,
    pub rows: [Vec<&'static str>; 5],
}

pub struct KeyboardState {
    row: usize,
    col: usize,
    layer: Layer,
    ctrl: CtrlMode,
    last_was_sentence_end: bool,
}

impl KeyboardState {
    pub const fn new() -> Self {
        Self {
            row: 1,
            col: 0,
            layer: Layer::Shift,
            ctrl: CtrlMode::Off,
            last_was_sentence_end: false,
        }
    }

    pub fn row_len(row: usize) -> usize {
        match row {
            0 => 3,  // Top Floating Pill: [PREV, NEXT, DONE]
            1 => 10, // q..p / Q..P / 1..0
            2 => 9,  // a..l / A..L
            3 => 9,  // SHIFT z..m BKSP
            4 => 5,  // [123/ABC] [#+=] [CTRL] [SPACE] [ENTER]
            _ => 10,
        }
    }

    pub fn set_auto_cap(&mut self, should_cap: bool) {
        if self.layer == Layer::Lower || self.layer == Layer::Shift {
            self.layer = if should_cap {
                Layer::Shift
            } else {
                Layer::Lower
            };
        }
    }

    pub fn on_key(&mut self, key_code: i32) -> Action {
        match key_code {
            KEYCODE_BACK => Action::Hide,
            KEYCODE_DPAD_UP => {
                self.move_cursor(-1, 0);
                Action::Redraw
            }
            KEYCODE_DPAD_DOWN => {
                self.move_cursor(1, 0);
                Action::Redraw
            }
            KEYCODE_DPAD_LEFT => {
                self.move_cursor(0, -1);
                Action::Redraw
            }
            KEYCODE_DPAD_RIGHT => {
                self.move_cursor(0, 1);
                Action::Redraw
            }
            KEYCODE_DPAD_CENTER | KEYCODE_ENTER | KEYCODE_NUMPAD_ENTER => self.activate_current(),
            KEYCODE_DEL => {
                self.last_was_sentence_end = false;
                if self.ctrl != CtrlMode::Off {
                    if self.ctrl == CtrlMode::OneShot {
                        self.ctrl = CtrlMode::Off;
                    }
                    return Action::Ctrl("BKSP".to_string());
                }
                Action::Backspace
            }
            _ => Action::Pass,
        }
    }

    fn move_cursor(&mut self, d_row: isize, d_col: isize) {
        let old_row = self.row;
        let new_row = (self.row as isize + d_row).clamp(0, 4) as usize;
        self.row = new_row;

        if old_row != new_row {
            self.col = match (old_row, new_row) {
                (1, 0) => match self.col {
                    0..=1 => 0,
                    2..=6 => 1,
                    _ => 2,
                },
                (0, 1) => match self.col {
                    0 => 0,
                    1 => 2,
                    _ => 9,
                },
                (1, 2) => self.col.min(8),
                (2, 1) => self.col,
                (2, 3) => self.col,
                (3, 2) => self.col,
                (3, 4) => match self.col {
                    0 => 0,
                    1 => 1,
                    2 => 2,
                    3..=6 => 3,
                    _ => 4,
                },
                (4, 3) => match self.col {
                    0 => 0,
                    1 => 1,
                    2 => 2,
                    3 => 4,
                    _ => 8,
                },
                _ => self.col.min(Self::row_len(new_row) - 1),
            };
        } else if d_col != 0 {
            let len = Self::row_len(self.row) as isize;
            self.col = (self.col as isize + d_col).rem_euclid(len) as usize;
        }
    }

    pub fn key_label(&self, r: usize, c: usize) -> &'static str {
        const PILL: [&str; 3] = ["PREV", "NEXT", "DONE"];

        const LOWER_R1: [&str; 10] = ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"];
        const LOWER_R2: [&str; 9] = ["a", "s", "d", "f", "g", "h", "j", "k", "l"];
        const LOWER_R3: [&str; 9] = ["SHIFT", "z", "x", "c", "v", "b", "n", "m", "BKSP"];

        const UPPER_R1: [&str; 10] = ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"];
        const UPPER_R2: [&str; 9] = ["A", "S", "D", "F", "G", "H", "J", "K", "L"];
        const UPPER_R3: [&str; 9] = ["SHIFT", "Z", "X", "C", "V", "B", "N", "M", "BKSP"];

        const NUM_R1: [&str; 10] = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"];
        const NUM_R2: [&str; 9] = ["-", "/", ":", ";", "(", ")", "$", "&", "@"];
        const NUM_R3: [&str; 9] = ["#+=_L", ".", ",", "?", "!", "'", "\"", "_", "BKSP"];

        const SYM_R1: [&str; 10] = ["[", "]", "{", "}", "#", "%", "^", "*", "+", "="];
        const SYM_R2: [&str; 9] = ["_", "\\", "|", "~", "<", ">", "€", "£", "₹"];
        const SYM_R3: [&str; 9] = ["123_L", ".", ",", "?", "!", "'", "\"", "•", "BKSP"];

        match r {
            0 => PILL[c.min(2)],
            1 => match self.layer {
                Layer::Lower => LOWER_R1[c],
                Layer::Shift | Layer::CapsLock => UPPER_R1[c],
                Layer::Numbers => NUM_R1[c],
                Layer::Symbols => SYM_R1[c],
            },
            2 => match self.layer {
                Layer::Lower => LOWER_R2[c],
                Layer::Shift | Layer::CapsLock => UPPER_R2[c],
                Layer::Numbers => NUM_R2[c],
                Layer::Symbols => SYM_R2[c],
            },
            3 => match self.layer {
                Layer::Lower => LOWER_R3[c],
                Layer::Shift | Layer::CapsLock => UPPER_R3[c],
                Layer::Numbers => NUM_R3[c],
                Layer::Symbols => SYM_R3[c],
            },
            4 => match c {
                0 => match self.layer {
                    Layer::Numbers | Layer::Symbols => "ABC",
                    _ => "123",
                },
                1 => match self.layer {
                    Layer::Symbols => "123",
                    _ => "#+=",
                },
                2 => "CTRL",
                3 => "SPACE",
                _ => "ENTER",
            },
            _ => "",
        }
    }

    fn activate_current(&mut self) -> Action {
        let key = self.key_label(self.row, self.col);
        match key {
            "PREV" => Action::CursorLeft,
            "NEXT" => Action::CursorRight,
            "DONE" => Action::Hide,
            "CTRL" => {
                self.ctrl = match self.ctrl {
                    CtrlMode::Off => CtrlMode::OneShot,
                    CtrlMode::OneShot => CtrlMode::Locked,
                    CtrlMode::Locked => CtrlMode::Off,
                };
                if self.ctrl != CtrlMode::Off
                    && (self.layer == Layer::Numbers || self.layer == Layer::Symbols)
                {
                    self.layer = Layer::Lower;
                }
                Action::Redraw
            }
            "SHIFT" => {
                self.layer = match self.layer {
                    Layer::Lower => Layer::Shift,
                    Layer::Shift => Layer::CapsLock,
                    Layer::CapsLock => Layer::Lower,
                    Layer::Numbers => Layer::Symbols,
                    Layer::Symbols => Layer::Numbers,
                };
                Action::Redraw
            }
            "123" | "123_L" => {
                self.ctrl = CtrlMode::Off;
                self.layer = Layer::Numbers;
                Action::Redraw
            }
            "#+=" | "#+=_L" => {
                self.ctrl = CtrlMode::Off;
                self.layer = Layer::Symbols;
                Action::Redraw
            }
            "ABC" => {
                self.layer = Layer::Lower;
                Action::Redraw
            }
            "BKSP" => {
                self.last_was_sentence_end = false;
                if self.ctrl != CtrlMode::Off {
                    if self.ctrl == CtrlMode::OneShot {
                        self.ctrl = CtrlMode::Off;
                    }
                    return Action::Ctrl("BKSP".to_string());
                }
                Action::Backspace
            }
            "SPACE" => {
                if self.ctrl == CtrlMode::OneShot {
                    self.ctrl = CtrlMode::Off;
                }
                if self.last_was_sentence_end && self.layer == Layer::Lower {
                    self.layer = Layer::Shift;
                }
                self.last_was_sentence_end = false;
                Action::Commit(" ".to_string())
            }
            "ENTER" => {
                self.ctrl = CtrlMode::Off;
                self.last_was_sentence_end = false;
                Action::Submit
            }
            ch => {
                if self.ctrl != CtrlMode::Off {
                    if self.ctrl == CtrlMode::OneShot {
                        self.ctrl = CtrlMode::Off;
                    }
                    return Action::Ctrl(ch.to_ascii_uppercase());
                }

                let committed = ch.to_string();
                self.last_was_sentence_end = matches!(ch, "." | "!" | "?");

                if self.layer == Layer::Shift {
                    self.layer = Layer::Lower;
                }
                Action::Commit(committed)
            }
        }
    }

    pub fn snapshot(&self) -> GridSnapshot {
        let mut rows: [Vec<&'static str>; 5] = [
            Vec::with_capacity(3),
            Vec::with_capacity(10),
            Vec::with_capacity(9),
            Vec::with_capacity(9),
            Vec::with_capacity(5),
        ];
        for r in 0..=4 {
            let len = Self::row_len(r);
            for c in 0..len {
                rows[r].push(self.key_label(r, c));
            }
        }
        GridSnapshot {
            focus_row: self.row,
            focus_col: self.col,
            layer: self.layer,
            ctrl: self.ctrl,
            rows,
        }
    }
}

pub static STATE: Mutex<KeyboardState> = Mutex::new(KeyboardState::new());
""",

    "src/input.rs": r"""use jni::objects::{
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
""",

    "src/renderer.rs": r"""use crate::state::{CtrlMode, GridSnapshot, Layer};
use jni::objects::{GlobalRef, JClass, JMethodID, JObject, JValue, JValueOwned};
use jni::signature::{Primitive, ReturnType};
use jni::JNIEnv;
use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};

struct RenderJniCache {
    paint_set_color: JMethodID,
    paint_set_stroke_width: JMethodID,
    paint_set_text_size: JMethodID,
    paint_set_shadow_layer: JMethodID,
    paint_set_shader: JMethodID,
    paint_ascent: JMethodID,
    paint_descent: JMethodID,
    canvas_draw_round_rect: JMethodID,
    canvas_draw_line: JMethodID,
    canvas_draw_text: JMethodID,
    canvas_draw_path: JMethodID,
    path_reset: JMethodID,
    path_move_to: JMethodID,
    path_line_to: JMethodID,
    path_close: JMethodID,
    grad_class: GlobalRef,
    grad_ctor: JMethodID,
    tile_clamp: GlobalRef,
    strings: Mutex<HashMap<&'static str, GlobalRef>>,
}

static RENDER_CACHE: OnceLock<RenderJniCache> = OnceLock::new();

fn cache<'a>(env: &mut JNIEnv<'a>) -> &'a RenderJniCache {
    RENDER_CACHE.get_or_init(|| {
        let grad_cls = env.find_class("android/graphics/LinearGradient").unwrap();
        let grad_class = env.new_global_ref(&grad_cls).unwrap();
        let _ = env.delete_local_ref(grad_cls);

        let clamp_obj = env
            .get_static_field(
                "android/graphics/Shader$TileMode",
                "CLAMP",
                "Landroid/graphics/Shader$TileMode;",
            )
            .unwrap()
            .l()
            .unwrap();
        let tile_clamp = env.new_global_ref(&clamp_obj).unwrap();
        let _ = env.delete_local_ref(clamp_obj);

        RenderJniCache {
            paint_set_color: env
                .get_method_id("android/graphics/Paint", "setColor", "(I)V")
                .unwrap(),
            paint_set_stroke_width: env
                .get_method_id("android/graphics/Paint", "setStrokeWidth", "(F)V")
                .unwrap(),
            paint_set_text_size: env
                .get_method_id("android/graphics/Paint", "setTextSize", "(F)V")
                .unwrap(),
            paint_set_shadow_layer: env
                .get_method_id("android/graphics/Paint", "setShadowLayer", "(FFFI)V")
                .unwrap(),
            paint_set_shader: env
                .get_method_id(
                    "android/graphics/Paint",
                    "setShader",
                    "(Landroid/graphics/Shader;)Landroid/graphics/Shader;",
                )
                .unwrap(),
            paint_ascent: env
                .get_method_id("android/graphics/Paint", "ascent", "()F")
                .unwrap(),
            paint_descent: env
                .get_method_id("android/graphics/Paint", "descent", "()F")
                .unwrap(),
            canvas_draw_round_rect: env
                .get_method_id(
                    "android/graphics/Canvas",
                    "drawRoundRect",
                    "(FFFFFFLandroid/graphics/Paint;)V",
                )
                .unwrap(),
            canvas_draw_line: env
                .get_method_id(
                    "android/graphics/Canvas",
                    "drawLine",
                    "(FFFFLandroid/graphics/Paint;)V",
                )
                .unwrap(),
            canvas_draw_text: env
                .get_method_id(
                    "android/graphics/Canvas",
                    "drawText",
                    "(Ljava/lang/String;FFLandroid/graphics/Paint;)V",
                )
                .unwrap(),
            canvas_draw_path: env
                .get_method_id(
                    "android/graphics/Canvas",
                    "drawPath",
                    "(Landroid/graphics/Path;Landroid/graphics/Paint;)V",
                )
                .unwrap(),
            path_reset: env
                .get_method_id("android/graphics/Path", "reset", "()V")
                .unwrap(),
            path_move_to: env
                .get_method_id("android/graphics/Path", "moveTo", "(FF)V")
                .unwrap(),
            path_line_to: env
                .get_method_id("android/graphics/Path", "lineTo", "(FF)V")
                .unwrap(),
            path_close: env
                .get_method_id("android/graphics/Path", "close", "()V")
                .unwrap(),
            grad_class,
            grad_ctor: env
                .get_method_id(
                    "android/graphics/LinearGradient",
                    "<init>",
                    "(FFFFIILandroid/graphics/Shader$TileMode;)V",
                )
                .unwrap(),
            tile_clamp,
            strings: Mutex::new(HashMap::with_capacity(96)),
        }
    })
}

#[inline]
fn set_color(env: &mut JNIEnv, c: &RenderJniCache, paint: &JObject, color: u32) {
    let _ = unsafe {
        env.call_method_unchecked(
            paint,
            c.paint_set_color,
            ReturnType::Primitive(Primitive::Void),
            &[JValue::Int(color as i32).as_jni()],
        )
    };
}

#[inline]
fn set_stroke_width(env: &mut JNIEnv, c: &RenderJniCache, paint: &JObject, width: f32) {
    let _ = unsafe {
        env.call_method_unchecked(
            paint,
            c.paint_set_stroke_width,
            ReturnType::Primitive(Primitive::Void),
            &[JValue::Float(width).as_jni()],
        )
    };
}

#[inline]
fn set_text_size(env: &mut JNIEnv, c: &RenderJniCache, paint: &JObject, size: f32) {
    let _ = unsafe {
        env.call_method_unchecked(
            paint,
            c.paint_set_text_size,
            ReturnType::Primitive(Primitive::Void),
            &[JValue::Float(size).as_jni()],
        )
    };
}

#[inline]
fn set_shadow(
    env: &mut JNIEnv,
    c: &RenderJniCache,
    paint: &JObject,
    radius: f32,
    dx: f32,
    dy: f32,
    color: u32,
) {
    let _ = unsafe {
        env.call_method_unchecked(
            paint,
            c.paint_set_shadow_layer,
            ReturnType::Primitive(Primitive::Void),
            &[
                JValue::Float(radius).as_jni(),
                JValue::Float(dx).as_jni(),
                JValue::Float(dy).as_jni(),
                JValue::Int(color as i32).as_jni(),
            ],
        )
    };
}

#[inline]
fn clear_shadow(env: &mut JNIEnv, c: &RenderJniCache, paint: &JObject) {
    set_shadow(env, c, paint, 0.0, 0.0, 0.0, 0);
}

#[allow(clippy::too_many_arguments)]
fn set_gradient(
    env: &mut JNIEnv,
    c: &RenderJniCache,
    paint: &JObject,
    x0: f32,
    y0: f32,
    x1: f32,
    y1: f32,
    c0: u32,
    c1: u32,
) {
    let grad_cls = unsafe { JClass::from_raw(c.grad_class.as_raw()) };
    let grad = unsafe {
        env.new_object_unchecked(
            &grad_cls,
            c.grad_ctor,
            &[
                JValue::Float(x0).as_jni(),
                JValue::Float(y0).as_jni(),
                JValue::Float(x1).as_jni(),
                JValue::Float(y1).as_jni(),
                JValue::Int(c0 as i32).as_jni(),
                JValue::Int(c1 as i32).as_jni(),
                JValue::Object(c.tile_clamp.as_obj()).as_jni(),
            ],
        )
    };
    if let Ok(grad) = grad {
        let old = unsafe {
            env.call_method_unchecked(
                paint,
                c.paint_set_shader,
                ReturnType::Object,
                &[JValue::Object(&grad).as_jni()],
            )
        };
        if let Ok(JValueOwned::Object(old)) = old {
            let _ = env.delete_local_ref(old);
        }
        let _ = env.delete_local_ref(grad);
    }
}

#[inline]
fn clear_shader(env: &mut JNIEnv, c: &RenderJniCache, paint: &JObject) {
    let null_obj = JObject::null();
    let old = unsafe {
        env.call_method_unchecked(
            paint,
            c.paint_set_shader,
            ReturnType::Object,
            &[JValue::Object(&null_obj).as_jni()],
        )
    };
    if let Ok(JValueOwned::Object(old)) = old {
        let _ = env.delete_local_ref(old);
    }
}

#[inline]
#[allow(clippy::too_many_arguments)]
fn draw_round_rect(
    env: &mut JNIEnv,
    c: &RenderJniCache,
    canvas: &JObject,
    l: f32,
    t: f32,
    r: f32,
    b: f32,
    rad: f32,
    paint: &JObject,
) {
    let _ = unsafe {
        env.call_method_unchecked(
            canvas,
            c.canvas_draw_round_rect,
            ReturnType::Primitive(Primitive::Void),
            &[
                JValue::Float(l).as_jni(),
                JValue::Float(t).as_jni(),
                JValue::Float(r).as_jni(),
                JValue::Float(b).as_jni(),
                JValue::Float(rad).as_jni(),
                JValue::Float(rad).as_jni(),
                JValue::Object(paint).as_jni(),
            ],
        )
    };
}

#[inline]
#[allow(clippy::too_many_arguments)]
fn draw_line(
    env: &mut JNIEnv,
    c: &RenderJniCache,
    canvas: &JObject,
    x1: f32,
    y1: f32,
    x2: f32,
    y2: f32,
    paint: &JObject,
) {
    let _ = unsafe {
        env.call_method_unchecked(
            canvas,
            c.canvas_draw_line,
            ReturnType::Primitive(Primitive::Void),
            &[
                JValue::Float(x1).as_jni(),
                JValue::Float(y1).as_jni(),
                JValue::Float(x2).as_jni(),
                JValue::Float(y2).as_jni(),
                JValue::Object(paint).as_jni(),
            ],
        )
    };
}

fn draw_text_centered(
    env: &mut JNIEnv,
    c: &RenderJniCache,
    canvas: &JObject,
    text: &'static str,
    cx: f32,
    cy: f32,
    paint: &JObject,
) {
    let ascent = unsafe {
        env.call_method_unchecked(
            paint,
            c.paint_ascent,
            ReturnType::Primitive(Primitive::Float),
            &[],
        )
    }
    .and_then(|v| v.f())
    .unwrap_or(-18.0);
    let descent = unsafe {
        env.call_method_unchecked(
            paint,
            c.paint_descent,
            ReturnType::Primitive(Primitive::Float),
            &[],
        )
    }
    .and_then(|v| v.f())
    .unwrap_or(5.0);
    let text_y = cy - (ascent + descent) * 0.5;

    let mut map = c.strings.lock().unwrap();
    let gref = if let Some(existing) = map.get(text) {
        existing
    } else {
        let jstr = env.new_string(text).unwrap();
        let g = env.new_global_ref(&jstr).unwrap();
        let _ = env.delete_local_ref(jstr);
        map.insert(text, g);
        map.get(text).unwrap()
    };

    let _ = unsafe {
        env.call_method_unchecked(
            canvas,
            c.canvas_draw_text,
            ReturnType::Primitive(Primitive::Void),
            &[
                JValue::Object(gref.as_obj()).as_jni(),
                JValue::Float(cx).as_jni(),
                JValue::Float(text_y).as_jni(),
                JValue::Object(paint).as_jni(),
            ],
        )
    };
}

#[inline]
fn path_reset(env: &mut JNIEnv, c: &RenderJniCache, path: &JObject) {
    let _ = unsafe {
        env.call_method_unchecked(path, c.path_reset, ReturnType::Primitive(Primitive::Void), &[])
    };
}

#[inline]
fn path_move_to(env: &mut JNIEnv, c: &RenderJniCache, path: &JObject, x: f32, y: f32) {
    let _ = unsafe {
        env.call_method_unchecked(
            path,
            c.path_move_to,
            ReturnType::Primitive(Primitive::Void),
            &[JValue::Float(x).as_jni(), JValue::Float(y).as_jni()],
        )
    };
}

#[inline]
fn path_line_to(env: &mut JNIEnv, c: &RenderJniCache, path: &JObject, x: f32, y: f32) {
    let _ = unsafe {
        env.call_method_unchecked(
            path,
            c.path_line_to,
            ReturnType::Primitive(Primitive::Void),
            &[JValue::Float(x).as_jni(), JValue::Float(y).as_jni()],
        )
    };
}

#[inline]
fn path_close(env: &mut JNIEnv, c: &RenderJniCache, path: &JObject) {
    let _ = unsafe {
        env.call_method_unchecked(path, c.path_close, ReturnType::Primitive(Primitive::Void), &[])
    };
}

#[inline]
fn draw_path(env: &mut JNIEnv, c: &RenderJniCache, canvas: &JObject, path: &JObject, paint: &JObject) {
    let _ = unsafe {
        env.call_method_unchecked(
            canvas,
            c.canvas_draw_path,
            ReturnType::Primitive(Primitive::Void),
            &[JValue::Object(path).as_jni(), JValue::Object(paint).as_jni()],
        )
    };
}

fn ctrl_badge_for_key(label: &str) -> Option<&'static str> {
    match label {
        "a" | "A" => Some("ALL"),
        "z" | "Z" => Some("UNDO"),
        "x" | "X" => Some("CUT"),
        "c" | "C" => Some("COPY"),
        "v" | "V" => Some("PASTE"),
        "y" | "Y" => Some("REDO"),
        _ => None,
    }
}

#[allow(clippy::too_many_arguments)]
pub fn draw_keyboard(
    env: &mut JNIEnv,
    canvas: &JObject,
    fill_paint: &JObject,
    stroke_paint: &JObject,
    path: &JObject,
    w: f32,
    h: f32,
    snap: &GridSnapshot,
) {
    let c = cache(env);
    let is_shift = snap.layer == Layer::Shift;
    let is_caps = snap.layer == Layer::CapsLock;
    let shift_or_caps = is_shift || is_caps;
    let is_ctrl = snap.ctrl != CtrlMode::Off;
    let is_ctrl_locked = snap.ctrl == CtrlMode::Locked;

    let outer_pad = 10.0;

    // 1. Top Detached Liquid Glass Accessory Pill (Row 0)
    let pill_h = h * 0.125;
    let pill_margin_x = outer_pad + (w - outer_pad * 2.0) * 0.03;
    let pill_l = pill_margin_x;
    let pill_t = outer_pad;
    let pill_r = w - pill_margin_x;
    let pill_b = outer_pad + pill_h;
    let pill_rad = pill_h * 0.5;

    set_gradient(env, c, fill_paint, 0.0, pill_t, 0.0, pill_b, 0xA81A2636, 0x960E1620);
    set_shadow(env, c, fill_paint, 12.0, 0.0, 4.0, 0x77000000);
    draw_round_rect(env, c, canvas, pill_l, pill_t, pill_r, pill_b, pill_rad, fill_paint);
    clear_shadow(env, c, fill_paint);

    set_stroke_width(env, c, stroke_paint, 1.5);
    set_gradient(env, c, stroke_paint, pill_l, pill_t, pill_r, pill_b, 0x99FFFFFF, 0x44FFFFFF);
    draw_round_rect(env, c, canvas, pill_l, pill_t, pill_r, pill_b, pill_rad, stroke_paint);
    clear_shader(env, c, stroke_paint);

    let pill_btn_w = pill_h * 1.3;
    let pill_cy = (pill_t + pill_b) * 0.5;
    let pill_centers = [
        pill_l + pill_btn_w * 0.55,
        pill_l + pill_btn_w * 1.65,
        pill_r - pill_btn_w * 0.55,
    ];

    for (idx, &cx) in pill_centers.iter().enumerate() {
        let is_focused = snap.focus_row == 0 && snap.focus_col == idx;
        let bl = cx - pill_btn_w * 0.44;
        let bt = pill_t + 4.0;
        let br = cx + pill_btn_w * 0.44;
        let bb = pill_b - 4.0;

        if is_focused {
            set_gradient(env, c, fill_paint, bl, bt, bl, bb, 0x77FFFFFF, 0x44FFFFFF);
            draw_round_rect(env, c, canvas, bl, bt, br, bb, pill_rad, fill_paint);
            set_stroke_width(env, c, stroke_paint, 2.2);
            set_color(env, c, stroke_paint, 0xFFFFFFFF);
            draw_round_rect(env, c, canvas, bl, bt, br, bb, pill_rad, stroke_paint);
        } else if idx == 0 {
            set_gradient(env, c, fill_paint, bl, bt, bl, bb, 0x28FFFFFF, 0x18FFFFFF);
            draw_round_rect(env, c, canvas, bl, bt, br, bb, pill_rad, fill_paint);
        }

        set_stroke_width(env, c, stroke_paint, 2.4);
        set_color(env, c, stroke_paint, if is_focused { 0xFFFFFFFF } else { 0xCCFFFFFF });
        let s = pill_h * 0.15;
        path_reset(env, c, path);
        if idx == 0 {
            path_move_to(env, c, path, cx - s * 1.2, pill_cy + s * 0.45);
            path_line_to(env, c, path, cx, pill_cy - s * 0.65);
            path_line_to(env, c, path, cx + s * 1.2, pill_cy + s * 0.45);
        } else if idx == 1 {
            path_move_to(env, c, path, cx - s * 1.2, pill_cy - s * 0.45);
            path_line_to(env, c, path, cx, pill_cy + s * 0.65);
            path_line_to(env, c, path, cx + s * 1.2, pill_cy - s * 0.45);
        } else {
            path_move_to(env, c, path, cx - s * 1.2, pill_cy + s * 0.1);
            path_line_to(env, c, path, cx - s * 0.3, pill_cy + s * 0.95);
            path_line_to(env, c, path, cx + s * 1.35, pill_cy - s * 0.85);
        }
        draw_path(env, c, canvas, path, stroke_paint);
    }

    // 2. Main Dark Frosted Glass Keyboard Card
    let card_top = outer_pad + pill_h + (h * 0.025);
    let card_bot = h - outer_pad;
    let card_l = outer_pad;
    let card_r = w - outer_pad;
    let card_rad = 32.0;

    set_gradient(env, c, fill_paint, 0.0, card_top, 0.0, card_bot, 0xDC101822, 0xF006090E);
    set_shadow(env, c, fill_paint, 18.0, 0.0, 8.0, 0x99000000);
    draw_round_rect(env, c, canvas, card_l, card_top, card_r, card_bot, card_rad, fill_paint);
    clear_shadow(env, c, fill_paint);

    set_stroke_width(env, c, stroke_paint, 1.6);
    set_gradient(env, c, stroke_paint, card_l, card_top, card_r, card_bot, 0x77FFFFFF, 0x33FFFFFF);
    draw_round_rect(env, c, canvas, card_l, card_top, card_r, card_bot, card_rad, stroke_paint);
    clear_shader(env, c, stroke_paint);

    // 3. Key Grid (Rows 1..4)
    let pad_x = outer_pad + 20.0;
    let pad_y = 16.0;
    let grid_top = card_top + pad_y;
    let grid_bot = card_bot - pad_y;
    let grid_h = grid_bot - grid_top;
    let grid_w = (w - outer_pad * 2.0) - 40.0;

    let row_h = grid_h / 4.0;
    let unit_w = grid_w / 10.0;
    let gap_x = 10.5;
    let gap_y = 10.5;
    let key_corner = 12.0;

    for r in 1..=4 {
        let keys = &snap.rows[r];
        let y_top = grid_top + (r as f32 - 1.0) * row_h + gap_y * 0.5;
        let y_bot = grid_top + (r as f32) * row_h - gap_y * 0.5;

        for (col_idx, &raw_label) in keys.iter().enumerate() {
            let (x_left, x_right) = if r == 1 {
                let xl = pad_x + (col_idx as f32) * unit_w;
                (xl, xl + unit_w)
            } else if r == 2 {
                let xl = pad_x + (0.5 + col_idx as f32) * unit_w;
                (xl, xl + unit_w)
            } else if r == 3 {
                if col_idx == 0 {
                    (pad_x, pad_x + unit_w * 1.32)
                } else if col_idx == 8 {
                    let xr = pad_x + grid_w;
                    (xr - unit_w * 1.32, xr)
                } else {
                    let xl = pad_x + (1.5 + (col_idx as f32 - 1.0)) * unit_w;
                    (xl, xl + unit_w)
                }
            } else if col_idx == 0 {
                (pad_x, pad_x + unit_w * 1.25)
            } else if col_idx == 1 {
                (pad_x + unit_w * 1.25, pad_x + unit_w * 2.50)
            } else if col_idx == 2 {
                (pad_x + unit_w * 2.50, pad_x + unit_w * 3.80)
            } else if col_idx == 3 {
                (pad_x + unit_w * 3.80, pad_x + unit_w * 7.70)
            } else {
                (pad_x + unit_w * 7.70, pad_x + grid_w)
            };

            let kl = x_left + gap_x * 0.5;
            let kt = y_top;
            let kr = x_right - gap_x * 0.5;
            let kb = y_bot;

            let label = raw_label.trim_end_matches("_L");
            let is_focused = r == snap.focus_row && col_idx == snap.focus_col;
            let is_shift_key = label == "SHIFT";
            let is_ctrl_key = label == "CTRL";
            let is_mod_lit = (is_shift_key && shift_or_caps) || (is_ctrl_key && is_ctrl);
            let ctrl_badge = if is_ctrl { ctrl_badge_for_key(label) } else { None };

            if is_mod_lit {
                clear_shader(env, c, fill_paint);
                set_color(env, c, fill_paint, 0xF2FFFFFF);
                draw_round_rect(env, c, canvas, kl, kt, kr, kb, key_corner, fill_paint);
                if is_focused {
                    set_stroke_width(env, c, stroke_paint, 2.4);
                    set_color(env, c, stroke_paint, 0xFF38BDF8);
                    draw_round_rect(
                        env,
                        c,
                        canvas,
                        kl - 1.8,
                        kt - 1.8,
                        kr + 1.8,
                        kb + 1.8,
                        key_corner,
                        stroke_paint,
                    );
                }
            } else if is_focused {
                set_gradient(env, c, fill_paint, kl, kt, kl, kb, 0x70FFFFFF, 0x40FFFFFF);
                set_shadow(env, c, fill_paint, 10.0, 0.0, 2.0, 0x66FFFFFF);
                draw_round_rect(
                    env,
                    c,
                    canvas,
                    kl - 1.5,
                    kt - 1.5,
                    kr + 1.5,
                    kb + 1.5,
                    key_corner,
                    fill_paint,
                );
                clear_shadow(env, c, fill_paint);

                set_stroke_width(env, c, stroke_paint, 2.2);
                set_color(env, c, stroke_paint, 0xFFFFFFFF);
                draw_round_rect(
                    env,
                    c,
                    canvas,
                    kl - 1.5,
                    kt - 1.5,
                    kr + 1.5,
                    kb + 1.5,
                    key_corner,
                    stroke_paint,
                );
            } else {
                let (c0, c1) = if ctrl_badge.is_some() {
                    (0x4438BDF8, 0x220284C7)
                } else {
                    (0x36FFFFFF, 0x20FFFFFF)
                };
                set_gradient(env, c, fill_paint, kl, kt, kl, kb, c0, c1);
                draw_round_rect(env, c, canvas, kl, kt, kr, kb, key_corner, fill_paint);

                set_stroke_width(
                    env,
                    c,
                    stroke_paint,
                    if ctrl_badge.is_some() { 1.6 } else { 1.1 },
                );
                set_color(
                    env,
                    c,
                    stroke_paint,
                    if ctrl_badge.is_some() {
                        0xAA38BDF8
                    } else {
                        0x32FFFFFF
                    },
                );
                draw_round_rect(env, c, canvas, kl, kt, kr, kb, key_corner, stroke_paint);
            }

            clear_shader(env, c, fill_paint);
            let cx = (kl + kr) * 0.5;
            let cy = (kt + kb) * 0.5;

            if is_shift_key {
                let icon_color = if shift_or_caps { 0xFF0F172A } else { 0xFFFFFFFF };
                draw_shift_icon(
                    env,
                    c,
                    canvas,
                    path,
                    fill_paint,
                    stroke_paint,
                    cx,
                    cy,
                    row_h * 0.21,
                    icon_color,
                    shift_or_caps,
                    is_caps,
                );
            } else if is_ctrl_key {
                set_color(
                    env,
                    c,
                    fill_paint,
                    if is_ctrl { 0xFF0F172A } else { 0xFFF8FAFC },
                );
                set_text_size(env, c, fill_paint, row_h * 0.27);
                let y_off = if is_ctrl_locked { -row_h * 0.05 } else { 0.0 };
                draw_text_centered(env, c, canvas, "Ctrl", cx, cy + y_off, fill_paint);

                if is_ctrl_locked {
                    set_color(env, c, fill_paint, 0xFF0F172A);
                    draw_round_rect(
                        env,
                        c,
                        canvas,
                        cx - row_h * 0.16,
                        kb - row_h * 0.15,
                        cx + row_h * 0.16,
                        kb - row_h * 0.09,
                        2.0,
                        fill_paint,
                    );
                }
            } else if label == "BKSP" {
                draw_backspace_icon(env, c, canvas, path, stroke_paint, cx, cy, row_h * 0.20);
            } else if label == "ENTER" {
                draw_return_icon(env, c, canvas, path, stroke_paint, cx, cy, row_h * 0.20);
            } else if label == "SPACE" {
                let badge = if is_ctrl_locked {
                    "CTRL LOCK"
                } else if is_ctrl {
                    "CTRL"
                } else if is_caps {
                    "CAPS"
                } else if is_shift {
                    "SHIFT"
                } else if snap.layer == Layer::Numbers {
                    "123"
                } else if snap.layer == Layer::Symbols {
                    "SYM"
                } else {
                    "en"
                };
                set_color(env, c, fill_paint, 0x99E2E8F0);
                set_text_size(env, c, fill_paint, row_h * 0.20);
                draw_text_centered(env, c, canvas, badge, kr - 24.0, kb - 13.0, fill_paint);
            } else {
                set_color(env, c, fill_paint, 0xFFF8FAFC);
                set_text_size(
                    env,
                    c,
                    fill_paint,
                    if label.len() >= 3 {
                        row_h * 0.27
                    } else {
                        row_h * 0.35
                    },
                );
                let y_off = if ctrl_badge.is_some() {
                    -row_h * 0.07
                } else {
                    0.0
                };
                draw_text_centered(env, c, canvas, label, cx, cy + y_off, fill_paint);

                if let Some(badge) = ctrl_badge {
                    set_color(env, c, fill_paint, 0xFF7DD3FC);
                    set_text_size(env, c, fill_paint, row_h * 0.15);
                    draw_text_centered(env, c, canvas, badge, cx, kb - 9.0, fill_paint);
                }
            }
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn draw_shift_icon(
    env: &mut JNIEnv,
    c: &RenderJniCache,
    canvas: &JObject,
    path: &JObject,
    fill_paint: &JObject,
    stroke_paint: &JObject,
    cx: f32,
    cy: f32,
    s: f32,
    color: u32,
    filled: bool,
    is_caps: bool,
) {
    let y_off = if is_caps { -s * 0.22 } else { 0.0 };
    path_reset(env, c, path);
    path_move_to(env, c, path, cx, cy - s * 0.90 + y_off);
    path_line_to(env, c, path, cx + s * 0.90, cy + y_off);
    path_line_to(env, c, path, cx + s * 0.38, cy + y_off);
    path_line_to(env, c, path, cx + s * 0.38, cy + s * 0.68 + y_off);
    path_line_to(env, c, path, cx - s * 0.38, cy + s * 0.68 + y_off);
    path_line_to(env, c, path, cx - s * 0.38, cy + y_off);
    path_line_to(env, c, path, cx - s * 0.90, cy + y_off);
    path_close(env, c, path);

    if filled {
        set_color(env, c, fill_paint, color);
        draw_path(env, c, canvas, path, fill_paint);
    } else {
        set_stroke_width(env, c, stroke_paint, 2.1);
        set_color(env, c, stroke_paint, color);
        draw_path(env, c, canvas, path, stroke_paint);
    }

    if is_caps {
        set_color(env, c, fill_paint, color);
        draw_round_rect(
            env,
            c,
            canvas,
            cx - s * 0.42,
            cy + s * 0.62,
            cx + s * 0.42,
            cy + s * 0.92,
            2.0,
            fill_paint,
        );
    }
}

#[allow(clippy::too_many_arguments)]
fn draw_backspace_icon(
    env: &mut JNIEnv,
    c: &RenderJniCache,
    canvas: &JObject,
    path: &JObject,
    stroke_paint: &JObject,
    cx: f32,
    cy: f32,
    s: f32,
) {
    set_stroke_width(env, c, stroke_paint, 2.1);
    set_color(env, c, stroke_paint, 0xFFFFFFFF);
    path_reset(env, c, path);
    path_move_to(env, c, path, cx - s * 1.15, cy);
    path_line_to(env, c, path, cx - s * 0.45, cy - s * 0.72);
    path_line_to(env, c, path, cx + s * 1.05, cy - s * 0.72);
    path_line_to(env, c, path, cx + s * 1.05, cy + s * 0.72);
    path_line_to(env, c, path, cx - s * 0.45, cy + s * 0.72);
    path_close(env, c, path);
    draw_path(env, c, canvas, path, stroke_paint);

    let x_off = cx + s * 0.25;
    let d = s * 0.30;
    draw_line(env, c, canvas, x_off - d, cy - d, x_off + d, cy + d, stroke_paint);
    draw_line(env, c, canvas, x_off + d, cy - d, x_off - d, cy + d, stroke_paint);
}

#[allow(clippy::too_many_arguments)]
fn draw_return_icon(
    env: &mut JNIEnv,
    c: &RenderJniCache,
    canvas: &JObject,
    path: &JObject,
    stroke_paint: &JObject,
    cx: f32,
    cy: f32,
    s: f32,
) {
    set_stroke_width(env, c, stroke_paint, 2.2);
    set_color(env, c, stroke_paint, 0xFFFFFFFF);
    path_reset(env, c, path);
    path_move_to(env, c, path, cx + s * 0.95, cy - s * 0.55);
    path_line_to(env, c, path, cx + s * 0.95, cy + s * 0.25);
    path_line_to(env, c, path, cx - s * 0.95, cy + s * 0.25);
    draw_path(env, c, canvas, path, stroke_paint);

    path_reset(env, c, path);
    path_move_to(env, c, path, cx - s * 0.45, cy - s * 0.22);
    path_line_to(env, c, path, cx - s * 0.95, cy + s * 0.25);
    path_line_to(env, c, path, cx - s * 0.45, cy + s * 0.72);
    draw_path(env, c, canvas, path, stroke_paint);
}
""",

    "AndroidManifest.xml": r"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.ferrostb.keyboard"
    android:versionCode="7"
    android:versionName="1.6">

    <uses-sdk android:minSdkVersion="26" android:targetSdkVersion="30" />

    <application
        android:label="FerroKey Liquid Glass"
        android:hardwareAccelerated="true">

        <service
            android:name=".FerroKeyboardService"
            android:label="FerroKey Liquid Glass"
            android:permission="android.permission.BIND_INPUT_METHOD"
            android:exported="true">
            <intent-filter>
                <action android:name="android.view.InputMethod" />
            </intent-filter>
            <meta-data
                android:name="android.view.im"
                android:resource="@xml/method" />
        </service>
    </application>
</manifest>
""",

    "res/xml/method.xml": r"""<?xml version="1.0" encoding="utf-8"?>
<input-method xmlns:android="http://schemas.android.com/apk/res/android"
    android:isDefault="true">
    <subtype
        android:label="English (US)"
        android:imeSubtypeLocale="en_US"
        android:imeSubtypeMode="keyboard" />
</input-method>
""",

    "java/com/ferrostb/keyboard/FerroKeyboardService.java": r"""package com.ferrostb.keyboard;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.inputmethodservice.InputMethodService;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.Window;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputConnection;
import android.widget.FrameLayout;

public class FerroKeyboardService extends InputMethodService {
    static { System.loadLibrary("ferrokey"); }

    public static native void nativeSyncAutoCap(InputConnection ic);
    public static native int nativeOnKey(InputConnection ic, EditorInfo info, int keyCode);
    public static native void nativeOnDraw(Canvas c, Paint fill, Paint stroke, Path p, int w, int h);

    private View glassView;
    private boolean pinned = false;
    private boolean allowHide = false;
    private InputConnection cachedIc;

    @Override public boolean onEvaluateFullscreenMode() { return false; }
    @Override public boolean onEvaluateInputViewShown() { return pinned || super.onEvaluateInputViewShown(); }
    @Override public boolean onShowInputRequested(int f, boolean c) { pinned = true; allowHide = false; return true; }

    private InputConnection ic() {
        InputConnection cur = getCurrentInputConnection();
        return (cur != null) ? cur : cachedIc;
    }

    @Override public void onWindowShown() {
        super.onWindowShown();
        pinned = true; allowHide = false;
        if (getCurrentInputConnection() != null) cachedIc = getCurrentInputConnection();
        nativeSyncAutoCap(ic());
        if (glassView != null) glassView.invalidate();
    }

    @Override public void onStartInput(EditorInfo a, boolean r) {
        super.onStartInput(a, r);
        if (getCurrentInputConnection() != null && a != null && a.inputType != 0) {
            cachedIc = getCurrentInputConnection();
            nativeSyncAutoCap(cachedIc);
        }
    }

    @Override public void onFinishInputView(boolean f) { if (allowHide || !pinned) super.onFinishInputView(f); }
    @Override public void hideWindow() {
        if (pinned && !allowHide) return;
        pinned = false; allowHide = false;
        super.hideWindow();
    }

    private void closeIme() { pinned = false; allowHide = true; requestHideSelf(0); super.hideWindow(); }

    @Override public void onComputeInsets(Insets out) {
        super.onComputeInsets(out);
        if (getWindow() != null && getWindow().getWindow() != null) {
            int h = getWindow().getWindow().getDecorView().getHeight();
            out.contentTopInsets = h; out.visibleTopInsets = h;
            out.touchableInsets = Insets.TOUCHABLE_INSETS_FRAME;
        }
    }

    @Override public View onCreateInputView() {
        Window win = getWindow().getWindow();
        if (win != null) win.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
        FrameLayout root = new FrameLayout(this);
        int sw = getResources().getDisplayMetrics().widthPixels;
        int sh = getResources().getDisplayMetrics().heightPixels;
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams((int)(sw * 0.52f), (int)(sh * 0.38f));
        lp.gravity = Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL;
        lp.bottomMargin = (int)(sh * 0.035f);
        glassView = new RustSurface(this);
        root.addView(glassView, lp);
        return root;
    }

    @Override public boolean onKeyDown(int code, KeyEvent ev) {
        if (!pinned && !isInputViewShown()) return super.onKeyDown(code, ev);
        int res = nativeOnKey(ic(), getCurrentInputEditorInfo(), code);
        if (res == 0) return super.onKeyDown(code, ev);
        if (res == 2) { closeIme(); return true; }
        if (glassView != null) glassView.invalidate();
        return true;
    }

    @Override public boolean onKeyUp(int c, KeyEvent e) {
        return ((pinned || isInputViewShown()) && (c == 4 || (c >= 19 && c <= 23) || c == 66 || c == 67 || c == 160)) || super.onKeyUp(c, e);
    }

    private static class RustSurface extends View {
        private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Path path = new Path();

        RustSurface(Context ctx) {
            super(ctx);
            setLayerType(LAYER_TYPE_SOFTWARE, null);
            fill.setStyle(Paint.Style.FILL);
            fill.setTextAlign(Paint.Align.CENTER);
            fill.setTypeface(Typeface.create("sans-serif", Typeface.NORMAL));
            stroke.setStyle(Paint.Style.STROKE);
            stroke.setStrokeCap(Paint.Cap.ROUND);
            stroke.setStrokeJoin(Paint.Join.ROUND);
        }

        @Override protected void onDraw(Canvas c) {
            nativeOnDraw(c, fill, stroke, path, getWidth(), getHeight());
        }
    }
}
""",

    ".github/workflows/build.yml": r"""name: Build FerroKey Liquid Glass APK

on:
  push:
    branches: [ "main", "master" ]
  workflow_dispatch:

jobs:
  build-apk:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Install Rust toolchain & Android targets
        uses: dtolnay/rust-toolchain@stable
        with:
          targets: armv7-linux-androideabi,aarch64-linux-android

      - name: Rust Cache
        uses: Swatinem/rust-cache@v2

      - name: Install cargo-ndk
        uses: taiki-e/install-action@v2
        with:
          tool: cargo-ndk

      - name: Compile Rust Liquid Glass Engine (.so)
        run: |
          cargo ndk -t armeabi-v7a -t arm64-v8a -o ./jniLibs build --release

      - name: Package & Sign Android APK
        run: |
          BT=$(ls -d "$ANDROID_HOME/build-tools/"* | sort -V | tail -n 1)
          PLATFORM=$(ls -d "$ANDROID_HOME/platforms/"* | sort -V | tail -n 1)

          mkdir -p build/classes build/apk/lib/armeabi-v7a build/apk/lib/arm64-v8a

          "$BT/aapt2" compile res/xml/method.xml -o build/
          "$BT/aapt2" link -o build/unsigned.apk \
            -I "$PLATFORM/android.jar" \
            --manifest AndroidManifest.xml \
            --java build/classes \
            build/xml_method.xml.flat

          javac -source 1.8 -target 1.8 \
            -bootclasspath "$PLATFORM/android.jar" \
            -d build/classes \
            java/com/ferrostb/keyboard/FerroKeyboardService.java \
            build/classes/com/ferrostb/keyboard/R.java

          "$BT/d8" --lib "$PLATFORM/android.jar" \
            --output build/apk \
            $(find build/classes -name "*.class")

          cp jniLibs/armeabi-v7a/libferrokey.so build/apk/lib/armeabi-v7a/
          cp jniLibs/arm64-v8a/libferrokey.so build/apk/lib/arm64-v8a/

          cd build/apk
          zip -u ../unsigned.apk classes.dex
          zip -u -0 -r ../unsigned.apk lib/
          cd ../..

          "$BT/zipalign" -f -p 4 build/unsigned.apk build/aligned.apk

          keytool -genkey -v \
            -keystore debug.keystore \
            -storepass android \
            -alias androiddebugkey \
            -keypass android \
            -keyalg RSA \
            -keysize 2048 \
            -validity 10000 \
            -dname "CN=FerroSTB,O=Android,C=US"

          "$BT/apksigner" sign \
            --ks debug.keystore \
            --ks-pass pass:android \
            --out ferrokey-liquid-glass.apk \
            build/aligned.apk

      - name: Upload Signed APK Artifact
        uses: actions/upload-artifact@v4
        with:
          name: ferrokey-liquid-glass-apk
          path: ferrokey-liquid-glass.apk
"""
}

for path, content in FILES.items():
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content.strip() + "\n")

print("[+] FerroKey v0.7 (OnceLock JMethodID + GlobalRef JString caching) generated!")
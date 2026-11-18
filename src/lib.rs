use jni::objects::JClass;
use jni::sys::{jint, jstring};
use jni::JNIEnv;
use std::sync::Mutex;

#[derive(Clone, Copy, PartialEq)]
enum Layer {
    Lower = 0,
    Shift = 1,    // Single-tap (or auto-cap): capitalizes 1 letter then reverts to Lower
    CapsLock = 2, // Double-tap: stays capitalized until toggled off
    Numbers = 3,
    Symbols = 4,
}

#[derive(Clone, Copy, PartialEq)]
enum CtrlMode {
    Off = 0,
    OneShot = 1, // Single-tap: fires one Ctrl+<key> combo then reverts to Off
    Locked = 2,  // Double-tap: stays active for repeated Ctrl+Z / Ctrl+V until toggled off
}

struct KeyboardState {
    row: usize,
    col: usize,
    layer: Layer,
    ctrl: CtrlMode,
    last_was_sentence_end: bool,
}

impl KeyboardState {
    const fn new() -> Self {
        Self {
            row: 1,
            col: 0,
            layer: Layer::Shift,
            ctrl: CtrlMode::Off,
            last_was_sentence_end: false,
        }
    }

    fn row_len(row: usize) -> usize {
        match row {
            0 => 3,  // Top Floating Pill: [PREV, NEXT, DONE]
            1 => 10, // q..p / Q..P / 1..0
            2 => 9,  // a..l / A..L
            3 => 9,  // SHIFT z..m BKSP
            4 => 5,  // [123/ABC] [#+=] [CTRL] [SPACE] [ENTER]
            _ => 10,
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
                    0 => 0,      // SHIFT -> 123
                    1 => 1,      // z -> #+=
                    2 => 2,      // x -> CTRL
                    3..=6 => 3,  // c..n -> SPACE
                    _ => 4,      // m, BKSP -> ENTER
                },
                (4, 3) => match self.col {
                    0 => 0,      // 123 -> SHIFT
                    1 => 1,      // #+= -> z
                    2 => 2,      // CTRL -> x (right in the z/x/c/v cluster)
                    3 => 4,      // SPACE -> v
                    _ => 8,      // ENTER -> BKSP
                },
                _ => self.col.min(Self::row_len(new_row) - 1),
            };
        } else if d_col != 0 {
            let len = Self::row_len(self.row) as isize;
            self.col = (self.col as isize + d_col).rem_euclid(len) as usize;
        }
    }

    fn key_label(&self, r: usize, c: usize) -> &'static str {
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

    fn activate_current(&mut self) -> String {
        let key = self.key_label(self.row, self.col);
        match key {
            "PREV" => "CURSOR_LEFT".to_string(),
            "NEXT" => "CURSOR_RIGHT".to_string(),
            "DONE" => "HIDE".to_string(),
            "CTRL" => {
                // Single tap: Off -> OneShot. Double tap: OneShot -> Locked. Third tap: Off.
                self.ctrl = match self.ctrl {
                    CtrlMode::Off => CtrlMode::OneShot,
                    CtrlMode::OneShot => CtrlMode::Locked,
                    CtrlMode::Locked => CtrlMode::Off,
                };
                // Switch back to letters automatically if user tapped Ctrl while on 123/#+=
                if self.ctrl != CtrlMode::Off
                    && (self.layer == Layer::Numbers || self.layer == Layer::Symbols)
                {
                    self.layer = Layer::Lower;
                }
                "REDRAW".to_string()
            }
            "SHIFT" => {
                self.layer = match self.layer {
                    Layer::Lower => Layer::Shift,
                    Layer::Shift => Layer::CapsLock,
                    Layer::CapsLock => Layer::Lower,
                    Layer::Numbers => Layer::Symbols,
                    Layer::Symbols => Layer::Numbers,
                };
                "REDRAW".to_string()
            }
            "123" | "123_L" => {
                self.ctrl = CtrlMode::Off;
                self.layer = Layer::Numbers;
                "REDRAW".to_string()
            }
            "#+=" | "#+=_L" => {
                self.ctrl = CtrlMode::Off;
                self.layer = Layer::Symbols;
                "REDRAW".to_string()
            }
            "ABC" => {
                self.layer = Layer::Lower;
                "REDRAW".to_string()
            }
            "BKSP" => {
                self.last_was_sentence_end = false;
                if self.ctrl != CtrlMode::Off {
                    if self.ctrl == CtrlMode::OneShot {
                        self.ctrl = CtrlMode::Off;
                    }
                    return "CTRL:BKSP".to_string();
                }
                "BACKSPACE".to_string()
            }
            "SPACE" => {
                if self.ctrl == CtrlMode::OneShot {
                    self.ctrl = CtrlMode::Off;
                }
                if self.last_was_sentence_end && self.layer == Layer::Lower {
                    self.layer = Layer::Shift;
                }
                self.last_was_sentence_end = false;
                "COMMIT: ".to_string()
            }
            "ENTER" => {
                self.ctrl = CtrlMode::Off;
                self.last_was_sentence_end = false;
                "SUBMIT".to_string()
            }
            ch => {
                if self.ctrl != CtrlMode::Off {
                    if self.ctrl == CtrlMode::OneShot {
                        self.ctrl = CtrlMode::Off;
                    }
                    let upper = ch.to_ascii_uppercase();
                    return format!("CTRL:{}", upper);
                }

                let committed = ch.to_string();
                self.last_was_sentence_end = matches!(ch, "." | "!" | "?");

                if self.layer == Layer::Shift {
                    self.layer = Layer::Lower;
                }
                "COMMIT:".to_string() + &committed
            }
        }
    }

    fn serialize_grid(&self) -> String {
        let layer_id = self.layer as u8;
        let ctrl_id = self.ctrl as u8;
        let mut out = format!("{},{},{},{}\n", self.row, self.col, layer_id, ctrl_id);
        for r in 0..=4 {
            let len = Self::row_len(r);
            let mut items = Vec::with_capacity(len);
            for c in 0..len {
                items.push(self.key_label(r, c));
            }
            out.push_str(&items.join("\t"));
            if r < 4 {
                out.push('\n');
            }
        }
        out
    }
}

static STATE: Mutex<KeyboardState> = Mutex::new(KeyboardState::new());

const KEYCODE_DPAD_UP: jint = 19;
const KEYCODE_DPAD_DOWN: jint = 20;
const KEYCODE_DPAD_LEFT: jint = 21;
const KEYCODE_DPAD_RIGHT: jint = 22;
const KEYCODE_DPAD_CENTER: jint = 23;
const KEYCODE_ENTER: jint = 66;
const KEYCODE_DEL: jint = 67;
const KEYCODE_NUMPAD_ENTER: jint = 160;

#[no_mangle]
pub extern "system" fn Java_com_ferrostb_keyboard_FerroKeyboardService_nativeOnKey(
    env: JNIEnv,
    _class: JClass,
    key_code: jint,
) -> jstring {
    let mut state = STATE.lock().unwrap();
    let response = match key_code {
        KEYCODE_DPAD_UP => {
            state.move_cursor(-1, 0);
            "REDRAW".to_string()
        }
        KEYCODE_DPAD_DOWN => {
            state.move_cursor(1, 0);
            "REDRAW".to_string()
        }
        KEYCODE_DPAD_LEFT => {
            state.move_cursor(0, -1);
            "REDRAW".to_string()
        }
        KEYCODE_DPAD_RIGHT => {
            state.move_cursor(0, 1);
            "REDRAW".to_string()
        }
        KEYCODE_DPAD_CENTER | KEYCODE_ENTER | KEYCODE_NUMPAD_ENTER => state.activate_current(),
        KEYCODE_DEL => {
            state.last_was_sentence_end = false;
            "BACKSPACE".to_string()
        }
        _ => "PASS".to_string(),
    };
    env.new_string(response).unwrap().into_raw()
}

#[no_mangle]
pub extern "system" fn Java_com_ferrostb_keyboard_FerroKeyboardService_nativeSetShiftState(
    _env: JNIEnv,
    _class: JClass,
    should_cap: jint,
) {
    let mut state = STATE.lock().unwrap();
    if state.layer == Layer::Lower || state.layer == Layer::Shift {
        state.layer = if should_cap != 0 {
            Layer::Shift
        } else {
            Layer::Lower
        };
    }
}

#[no_mangle]
pub extern "system" fn Java_com_ferrostb_keyboard_FerroKeyboardService_nativeGetGrid(
    env: JNIEnv,
    _class: JClass,
) -> jstring {
    let state = STATE.lock().unwrap();
    let payload = state.serialize_grid();
    env.new_string(payload).unwrap().into_raw()
}

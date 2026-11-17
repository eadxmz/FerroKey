use jni::objects::JClass;
use jni::sys::{jint, jstring};
use jni::JNIEnv;
use std::sync::Mutex;

#[derive(Clone, Copy, PartialEq)]
enum Layer {
    Lower,
    Upper,
    Numbers,
    Symbols,
}

struct KeyboardState {
    row: usize,
    col: usize,
    layer: Layer,
}

impl KeyboardState {
    const fn new() -> Self {
        Self {
            row: 1,
            col: 0,
            layer: Layer::Lower,
        }
    }

    fn row_len(row: usize) -> usize {
        match row {
            0 => 3,  // Top Floating Pill: [PREV, NEXT, DONE]
            1 => 10, // Q W E R T Y U I O P
            2 => 9,  // A S D F G H J K L
            3 => 9,  // SHIFT Z X C V B N M BKSP
            4 => 4,  // 123 SYM SPACE ENTER
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
                    0 => 0,
                    1 => 1,
                    2..=6 => 2,
                    _ => 3,
                },
                (4, 3) => match self.col {
                    0 => 0,
                    1 => 1,
                    2 => 4,
                    _ => 8,
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

        const ALPHA_R1: [&str; 10] = ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"];
        const ALPHA_R2: [&str; 9] = ["A", "S", "D", "F", "G", "H", "J", "K", "L"];
        const ALPHA_R3: [&str; 9] = ["SHIFT", "Z", "X", "C", "V", "B", "N", "M", "BKSP"];

        const NUM_R1: [&str; 10] = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"];
        const NUM_R2: [&str; 9] = ["-", "/", ":", ";", "(", ")", "$", "&", "@"];
        const NUM_R3: [&str; 9] = ["SHIFT", ".", ",", "?", "!", "'", "\"", "_", "BKSP"];

        const SYM_R1: [&str; 10] = ["[", "]", "{", "}", "#", "%", "^", "*", "+", "="];
        const SYM_R2: [&str; 9] = ["_", "\\", "|", "~", "<", ">", "€", "£", "₹"];
        const SYM_R3: [&str; 9] = ["SHIFT", ".", ",", "?", "!", "'", "\"", "•", "BKSP"];

        match r {
            0 => PILL[c.min(2)],
            1 => match self.layer {
                Layer::Lower | Layer::Upper => ALPHA_R1[c],
                Layer::Numbers => NUM_R1[c],
                Layer::Symbols => SYM_R1[c],
            },
            2 => match self.layer {
                Layer::Lower | Layer::Upper => ALPHA_R2[c],
                Layer::Numbers => NUM_R2[c],
                Layer::Symbols => SYM_R2[c],
            },
            3 => match self.layer {
                Layer::Lower | Layer::Upper => ALPHA_R3[c],
                Layer::Numbers => NUM_R3[c],
                Layer::Symbols => SYM_R3[c],
            },
            4 => match c {
                0 => match self.layer {
                    Layer::Numbers | Layer::Symbols => "ABC",
                    _ => "123",
                },
                1 => "SYM",
                2 => "SPACE",
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
            "SHIFT" => {
                self.layer = match self.layer {
                    Layer::Lower => Layer::Upper,
                    Layer::Upper => Layer::Lower,
                    Layer::Numbers => Layer::Symbols,
                    Layer::Symbols => Layer::Numbers,
                };
                "REDRAW".to_string()
            }
            "123" => {
                self.layer = Layer::Numbers;
                "REDRAW".to_string()
            }
            "ABC" => {
                self.layer = Layer::Lower;
                "REDRAW".to_string()
            }
            "SYM" => {
                self.layer = match self.layer {
                    Layer::Symbols => Layer::Lower,
                    _ => Layer::Symbols,
                };
                "REDRAW".to_string()
            }
            "BKSP" => "BACKSPACE".to_string(),
            "SPACE" => "COMMIT: ".to_string(),
            "ENTER" => "SUBMIT".to_string(),
            ch => {
                let out = if self.layer == Layer::Lower {
                    ch.to_ascii_lowercase()
                } else {
                    ch.to_string()
                };
                "COMMIT:".to_string() + &out
            }
        }
    }

    fn serialize_grid(&self) -> String {
        let shift_active = if self.layer == Layer::Upper || self.layer == Layer::Symbols {
            1
        } else {
            0
        };
        let mut out = format!("{},{},{}\n", self.row, self.col, shift_active);
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
        KEYCODE_DEL => "BACKSPACE".to_string(),
        _ => "PASS".to_string(),
    };
    env.new_string(response).unwrap().into_raw()
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

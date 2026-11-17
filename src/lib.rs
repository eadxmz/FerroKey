use jni::objects::JClass;
use jni::sys::{jint, jstring};
use jni::JNIEnv;
use std::sync::Mutex;

#[derive(Clone, Copy, PartialEq)]
enum Layer {
    Lower,
    Upper,
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
            0..=3 => 10,
            4 => 6, // [SYM, LEFT, SPACE, RIGHT, CLR, ENTER]
            _ => 10,
        }
    }

    fn move_cursor(&mut self, d_row: isize, d_col: isize) {
        let old_row = self.row;
        let new_row = (self.row as isize + d_row).clamp(0, 4) as usize;
        self.row = new_row;

        if old_row != new_row {
            if new_row == 4 {
                self.col = match self.col {
                    0..=1 => 0, // SYM
                    2 => 1,     // LEFT
                    3..=6 => 2, // SPACE
                    7 => 3,     // RIGHT
                    8 => 4,     // CLR
                    _ => 5,     // ENTER
                };
            } else if old_row == 4 {
                self.col = match self.col {
                    0 => 0,
                    1 => 2,
                    2 => 4,
                    3 => 7,
                    4 => 8,
                    _ => 9,
                };
            }
        } else {
            let len = Self::row_len(self.row) as isize;
            self.col = (self.col as isize + d_col).rem_euclid(len) as usize;
        }
    }

    fn key_at(&self, r: usize, c: usize) -> &'static str {
        const LOWER: [[&str; 10]; 4] = [
            ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
            ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
            ["a", "s", "d", "f", "g", "h", "j", "k", "l", "-"],
            ["SHIFT", "z", "x", "c", "v", "b", "n", "m", ".", "BKSP"],
        ];
        const UPPER: [[&str; 10]; 4] = [
            ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
            ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"],
            ["A", "S", "D", "F", "G", "H", "J", "K", "L", "_"],
            ["SHIFT", "Z", "X", "C", "V", "B", "N", "M", ",", "BKSP"],
        ];
        const SYM: [[&str; 10]; 4] = [
            ["!", "@", "#", "$", "%", "^", "&", "*", "(", ")"],
            ["~", "`", "|", "/", "\\", "=", "+", "[", "]", "?"],
            [":", ";", "\"", "'", "<", ">", "{", "}", "_", "-"],
            ["SHIFT", "€", "£", "₹", "©", "®", "°", "•", "…", "BKSP"],
        ];
        const BOTTOM: [&str; 6] = ["?!#", "◀", "SPACE", "▶", "CLR", "⏎"];

        if r == 4 {
            return BOTTOM[c.min(5)];
        }
        match self.layer {
            Layer::Lower => LOWER[r][c],
            Layer::Upper => UPPER[r][c],
            Layer::Symbols => SYM[r][c],
        }
    }

    fn activate_current(&mut self) -> String {
        let key = self.key_at(self.row, self.col);
        match key {
            "SHIFT" => {
                self.layer = match self.layer {
                    Layer::Lower => Layer::Upper,
                    Layer::Upper => Layer::Lower,
                    Layer::Symbols => Layer::Lower,
                };
                "REDRAW".to_string()
            }
            "?!#" => {
                self.layer = match self.layer {
                    Layer::Symbols => Layer::Lower,
                    _ => Layer::Symbols,
                };
                "REDRAW".to_string()
            }
            "BKSP" => "BACKSPACE".to_string(),
            "SPACE" => "COMMIT: ".to_string(),
            "◀" => "CURSOR_LEFT".to_string(),
            "▶" => "CURSOR_RIGHT".to_string(),
            "CLR" => "CLEAR".to_string(),
            "⏎" => "SUBMIT".to_string(),
            ch => format!("COMMIT:{}", ch),
        }
    }

    fn serialize_grid(&self) -> String {
        let mut out = format!("{},{}\n", self.row, self.col);
        for r in 0..4 {
            let mut row_items = Vec::with_capacity(10);
            for c in 0..10 {
                row_items.push(self.key_at(r, c));
            }
            out.push_str(&row_items.join("\t"));
            out.push('\n');
        }
        let mut bot_items = Vec::with_capacity(6);
        for c in 0..6 {
            bot_items.push(self.key_at(4, c));
        }
        out.push_str(&bot_items.join("\t"));
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
        KEYCODE_DPAD_CENTER | KEYCODE_ENTER => state.activate_current(),
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

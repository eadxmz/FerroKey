use std::sync::Mutex;

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

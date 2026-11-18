mod input;
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

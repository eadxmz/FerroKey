use crate::state::{CtrlMode, GridSnapshot, Layer};
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

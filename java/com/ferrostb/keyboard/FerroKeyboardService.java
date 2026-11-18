package com.ferrostb.keyboard;

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

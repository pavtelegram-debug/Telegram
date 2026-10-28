package org.telegram.ui;

import android.app.Activity;
import android.os.Bundle;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.content.Context;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;
import org.telegram.messenger.TelefostApi;

/**
 * Telefost's own-service entry point. It authenticates only Telefost accounts;
 * it intentionally does not collect or forward Telegram login codes.
 */
public class TelefostLoginActivity extends Activity {
    private TelefostApi api;
    private LinearLayout root, content;
    private EditText phoneInput, codeInput, usernameInput, nameInput, searchInput, messageInput;
    private String currentPeer = "";

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        api = new TelefostApi(this);
        showBase();
        if (api.isSignedIn()) showHome();
        else showLogin();
    }

    private void showBase() {
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(0, 0, 0, 0);
        root.setBackgroundColor(Color.rgb(23, 33, 43));
        setContentView(root);

        LinearLayout appBar = new LinearLayout(this);
        appBar.setGravity(Gravity.CENTER_VERTICAL);
        appBar.setPadding(dp(18), 0, dp(18), 0);
        appBar.setBackgroundColor(Color.rgb(36, 47, 61));
        TextView brand = new TextView(this);
        brand.setText("Telefost");
        brand.setTextColor(Color.WHITE);
        brand.setTextSize(20);
        brand.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        appBar.addView(brand, new LinearLayout.LayoutParams(0, dp(56), 1));
        root.addView(appBar, new LinearLayout.LayoutParams(-1, dp(56)));

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(16), dp(12), dp(16), dp(20));
        scroll.addView(content);
    }

    private void showLogin() {
        content.removeAllViews();
        content.setPadding(dp(22), dp(24), dp(22), dp(20));
        TextView logo = new TextView(this);
        logo.setText("Telefost");
        logo.setTextColor(Color.WHITE);
        logo.setTextSize(30);
        logo.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        logo.setGravity(Gravity.CENTER);
        content.addView(logo, new LinearLayout.LayoutParams(-1, dp(58)));
        TextView sub = note("Мессенджер для общения");
        sub.setGravity(Gravity.CENTER);
        content.addView(sub, new LinearLayout.LayoutParams(-1, dp(38)));
        title("Вход");
        note("Используй номер Telefost, который выдал бот. Это отдельный аккаунт Telefost.");
        phoneInput = input("Номер Telefost · +79…", false);
        usernameInput = input("Username · например user123", false);
        nameInput = input("Имя", false);
        Button request = button("Получить код в боте");
        content.addView(request);
        codeInput = input("Код подтверждения Telefost", false);
        Button verify = button("Продолжить");
        content.addView(verify);
        request.setOnClickListener(v -> {
            String phone = phoneInput.getText().toString().trim();
            if (phone.isEmpty()) { toast("Введи номер Telefost"); return; }
            request.setEnabled(false);
            api.requestCode(phone, new TelefostApi.Callback() {
                public void onSuccess(JSONObject result) {
                    request.setEnabled(true);
                    toast(result.optString("message", "Проверь личный чат с ботом Telefost."));
                }
                public void onError(String message) { request.setEnabled(true); toast(message); }
            });
        });
        verify.setOnClickListener(v -> {
            String phone = phoneInput.getText().toString().trim();
            String code = codeInput.getText().toString().trim();
            if (phone.isEmpty() || code.isEmpty()) { toast("Введи номер и код Telefost"); return; }
            verify.setEnabled(false);
            api.verifyCode(phone, code, usernameInput.getText().toString().trim(),
                    nameInput.getText().toString().trim(), new TelefostApi.Callback() {
                public void onSuccess(JSONObject result) { showHome(); }
                public void onError(String message) { verify.setEnabled(true); toast(message); }
            });
        });
    }

    private void showHome() {
        content.removeAllViews();
        content.setPadding(dp(0), dp(0), dp(0), dp(16));
        currentPeer = "";

        LinearLayout top = new LinearLayout(this);
        top.setGravity(Gravity.CENTER_VERTICAL);
        top.setPadding(dp(16), 0, dp(12), 0);
        top.setBackgroundColor(Color.rgb(36, 47, 61));
        TextView brand = new TextView(this);
        brand.setText("Telefost");
        brand.setTextColor(Color.WHITE);
        brand.setTextSize(21);
        brand.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        top.addView(brand, new LinearLayout.LayoutParams(0, dp(56), 1));
        Button profile = button("Профиль");
        LinearLayout.LayoutParams profileParams = new LinearLayout.LayoutParams(dp(104), dp(40));
        profile.setLayoutParams(profileParams);
        top.addView(profile);
        content.addView(top, new LinearLayout.LayoutParams(-1, dp(56)));
        profile.setOnClickListener(v -> showProfile());

        title("Сообщения");
        TextView results = note("Загружаю чаты…");
        results.setPadding(dp(16), dp(18), dp(16), dp(18));
        content.addView(results, new LinearLayout.LayoutParams(-1, -2));
        Button refresh = button("Обновить список");
        LinearLayout.LayoutParams rp = (LinearLayout.LayoutParams) refresh.getLayoutParams();
        rp.setMargins(dp(12), dp(4), dp(12), dp(8));
        refresh.setLayoutParams(rp);
        content.addView(refresh);

        refresh.setOnClickListener(v -> {
            results.setText("Загружаю чаты…");
            removeRowsAfter(results);
            api.getChats(new TelefostApi.Callback() {
                public void onSuccess(JSONObject data) {
                    JSONArray arr = data.optJSONArray("chats");
                    if (arr == null || arr.length() == 0) {
                        results.setText("Пока нет сообщений. Новые диалоги появятся здесь.");
                        return;
                    }
                    results.setText("");
                    attachChatButtons(data, results);
                }
                public void onError(String message) { results.setText("Не удалось загрузить чаты: " + message); }
            });
        });
        Button logout = button("Выйти из аккаунта");
        LinearLayout.LayoutParams lp = (LinearLayout.LayoutParams) logout.getLayoutParams();
        lp.setMargins(dp(12), dp(16), dp(12), 0);
        logout.setLayoutParams(lp);
        content.addView(logout);
        logout.setOnClickListener(v -> { api.signOut(); showLogin(); });
        refresh.performClick();
    }

    private void showProfile() {
        api.getMe(new TelefostApi.Callback() {
            public void onSuccess(JSONObject data) {
                JSONObject user = data.optJSONObject("user");
                if (user == null) { toast("Сервер не вернул профиль"); return; }
                content.removeAllViews();
                content.setPadding(dp(16), dp(12), dp(16), dp(20));
                title("Мой профиль");
                TextView avatar = new TextView(TelefostLoginActivity.this);
                String name = user.optString("display_name", "T");
                avatar.setText(name.isEmpty() ? "T" : name.substring(0, 1).toUpperCase());
                avatar.setTextColor(Color.WHITE);
                avatar.setTextSize(30);
                avatar.setGravity(Gravity.CENTER);
                GradientDrawable circle = new GradientDrawable();
                circle.setColor(Color.rgb(82, 136, 193));
                circle.setShape(GradientDrawable.OVAL);
                avatar.setBackground(circle);
                LinearLayout.LayoutParams avp = new LinearLayout.LayoutParams(dp(76), dp(76));
                avp.gravity = Gravity.CENTER_HORIZONTAL;
                avp.topMargin = dp(12);
                content.addView(avatar, avp);
                TextView display = note(name);
                display.setTextSize(21);
                display.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
                display.setGravity(Gravity.CENTER);
                content.addView(display);
                content.addView(note("ID Telefost: " + user.optString("id", "—")));
                content.addView(note("Username: @" + user.optString("username", "не задан")));
                content.addView(note("Номер: " + user.optString("phone", "—")));
                content.addView(note("Stars: " + user.optString("stars", "0")));
                content.addView(note("Premium: " + (user.optBoolean("premium") ? "Да" : "Нет")));
                Button back = button("Назад к сообщениям");
                content.addView(back);
                back.setOnClickListener(v -> showHome());
            }
            public void onError(String message) { toast(message); }
        });
    }

    private void removeRowsAfter(View anchor) {
        int index = content.indexOfChild(anchor);
        if (index >= 0) {
            while (content.getChildCount() > index + 1) {
                View child = content.getChildAt(index + 1);
                if (child instanceof Button && ((Button) child).getText().toString().equals("Обновить список")) break;
                content.removeViewAt(index + 1);
            }
        }
    }

    private void openChat(String peer) {
        currentPeer = peer;
        content.removeAllViews();
        title("Чат: " + peer);
        Button back = button("← Назад к чатам");
        content.addView(back);
        TextView history = note("Загружаю сообщения…");
        content.addView(history);
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        messageInput = input("Сообщение", false);
        row.addView(messageInput, new LinearLayout.LayoutParams(0, dp(52), 1));
        Button send = button("Отправить");
        row.addView(send);
        content.addView(row);
        back.setOnClickListener(v -> showHome());
        send.setOnClickListener(v -> {
            String text = messageInput.getText().toString().trim();
            if (text.isEmpty()) return;
            send.setEnabled(false);
            api.sendMessage(currentPeer, text, new TelefostApi.Callback() {
                public void onSuccess(JSONObject data) {
                    messageInput.setText("");
                    send.setEnabled(true);
                    loadHistory(history, currentPeer);
                }
                public void onError(String message) { send.setEnabled(true); toast(message); }
            });
        });
        loadHistory(history, peer);
    }

    private void loadHistory(TextView view, String peer) {
        api.getChat(peer, new TelefostApi.Callback() {
            public void onSuccess(JSONObject data) { view.setText(formatMessages(data)); }
            public void onError(String message) { view.setText(message); }
        });
    }

    private String formatChats(JSONObject data) {
        JSONArray arr = data.optJSONArray("chats");
        if (arr == null || arr.length() == 0) return "Пока нет чатов. Найди человека по юзернейму или номеру ниже.";
        StringBuilder b = new StringBuilder("Твои чаты:\n");
        for (int i=0;i<arr.length();i++) {
            JSONObject o = arr.optJSONObject(i);
            if (o != null) b.append("• ").append(o.optString("username", o.optString("peer", "пользователь")))
                    .append(" — ").append(o.optString("last_message", o.optString("body", ""))).append("\n");
        }
        return b.toString();
    }

    private String formatUsers(JSONObject data) {
        JSONArray arr = data.optJSONArray("users");
        if (arr == null || arr.length() == 0) return "Никого не нашёл. Проверь точный @юзернейм или номер.";
        StringBuilder b = new StringBuilder("Найденные пользователи (нажми кнопку ниже):\n");
        for (int i=0;i<arr.length();i++) {
            JSONObject o = arr.optJSONObject(i);
            if (o != null) b.append("• @").append(o.optString("username", "user"))
                    .append("  ").append(o.optString("phone", "")).append("\n");
        }
        return b.toString();
    }

    private String formatMessages(JSONObject data) {
        JSONArray arr = data.optJSONArray("messages");
        if (arr == null || arr.length() == 0) return "Сообщений пока нет. Напиши первое сообщение.";
        StringBuilder b = new StringBuilder();
        for (int i=0;i<arr.length();i++) {
            JSONObject o = arr.optJSONObject(i);
            if (o != null) b.append(o.optString("sender_phone", "user")).append(": ")
                    .append(o.optString("text", "")).append("\n\n");
        }
        return b.toString();
    }

    private void attachChatButtons(JSONObject data, TextView results) {
        JSONArray arr = data.optJSONArray("chats");
        if (arr == null) return;
        int index = content.indexOfChild(results) + 1;
        for (int i=0;i<arr.length();i++) {
            JSONObject o = arr.optJSONObject(i);
            if (o == null) continue;
            String peer = o.optString("username", o.optString("peer", o.optString("phone", "")));
            if (peer.isEmpty()) continue;
            LinearLayout row = new LinearLayout(this);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.setPadding(dp(14), dp(8), dp(14), dp(8));
            TextView avatar = new TextView(this);
            String letter = peer.replace("@", "");
            avatar.setText(letter.isEmpty() ? "?" : letter.substring(0, 1).toUpperCase());
            avatar.setTextColor(Color.WHITE); avatar.setTextSize(20); avatar.setGravity(Gravity.CENTER);
            GradientDrawable circle = new GradientDrawable();
            circle.setColor(Color.rgb(82, 136, 193)); circle.setShape(GradientDrawable.OVAL);
            avatar.setBackground(circle);
            row.addView(avatar, new LinearLayout.LayoutParams(dp(48), dp(48)));
            LinearLayout info = new LinearLayout(this);
            info.setOrientation(LinearLayout.VERTICAL);
            info.setPadding(dp(12), 0, 0, 0);
            TextView name = new TextView(this); name.setText("@" + peer);
            name.setTextColor(Color.WHITE); name.setTextSize(16); name.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
            TextView preview = new TextView(this);
            preview.setText(o.optString("last_message", o.optString("body", "Нажми, чтобы открыть чат")));
            preview.setTextColor(Color.rgb(160, 177, 194)); preview.setTextSize(13);
            info.addView(name); info.addView(preview);
            row.addView(info, new LinearLayout.LayoutParams(0, -2, 1));
            row.setBackgroundColor(Color.rgb(23, 33, 43));
            row.setOnClickListener(v -> openChat(peer));
            content.addView(row, index++);
            View divider = new View(this); divider.setBackgroundColor(Color.rgb(48, 62, 76));
            content.addView(divider, index++, new LinearLayout.LayoutParams(-1, dp(1)));
        }
    }

    private void attachUserButtons(JSONObject data, TextView results) {
        JSONArray arr = data.optJSONArray("users");
        if (arr == null) return;
        int index = content.indexOfChild(results) + 1;
        for (int i=0;i<arr.length();i++) {
            JSONObject o = arr.optJSONObject(i);
            if (o == null) continue;
            String peer = o.optString("username", o.optString("phone", ""));
            if (peer.isEmpty()) continue;
            LinearLayout row = new LinearLayout(this);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.setPadding(dp(14), dp(8), dp(14), dp(8));
            TextView avatar = new TextView(this);
            String letter = peer.replace("@", "");
            avatar.setText(letter.isEmpty() ? "?" : letter.substring(0, 1).toUpperCase());
            avatar.setTextColor(Color.WHITE); avatar.setTextSize(20); avatar.setGravity(Gravity.CENTER);
            GradientDrawable circle = new GradientDrawable();
            circle.setColor(Color.rgb(82, 136, 193)); circle.setShape(GradientDrawable.OVAL);
            avatar.setBackground(circle);
            row.addView(avatar, new LinearLayout.LayoutParams(dp(48), dp(48)));
            TextView name = new TextView(this);
            name.setText("@" + peer + "\\n" + o.optString("phone", "Пользователь Telefost"));
            name.setTextColor(Color.WHITE); name.setTextSize(16);
            name.setPadding(dp(12), 0, 0, 0);
            row.addView(name, new LinearLayout.LayoutParams(0, -2, 1));
            TextView action = new TextView(this); action.setText("›");
            action.setTextColor(Color.rgb(82, 136, 193)); action.setTextSize(28);
            row.addView(action);
            row.setOnClickListener(v -> openChat(peer));
            content.addView(row, index++);
            View divider = new View(this); divider.setBackgroundColor(Color.rgb(48, 62, 76));
            content.addView(divider, index++, new LinearLayout.LayoutParams(-1, dp(1)));
        }
    }

    private void title(String s) {
        TextView t = new TextView(this);
        t.setText(s); t.setTextColor(Color.WHITE); t.setTextSize(20);
        t.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        t.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, dp(48));
        p.topMargin = dp(4); p.bottomMargin = dp(6); content.addView(t, p);
    }

    private TextView note(String s) {
        TextView t = new TextView(this);
        t.setText(s); t.setTextColor(Color.rgb(222, 230, 237)); t.setTextSize(15);
        t.setPadding(dp(4), dp(10), dp(4), dp(10));
        return t;
    }

    private EditText input(String hint, boolean password) {
        EditText e = new EditText(this);
        e.setSingleLine(true); e.setHint(hint); e.setTextColor(Color.WHITE);
        e.setHintTextColor(Color.rgb(128, 146, 164));
        e.setPadding(dp(14), 0, dp(14), 0);
        GradientDrawable fieldBg = new GradientDrawable();
        fieldBg.setColor(Color.rgb(36, 47, 61));
        fieldBg.setCornerRadius(dp(10));
        e.setBackground(fieldBg);
        e.setTextSize(16);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, dp(52));
        p.topMargin = dp(8); content.addView(e, p);
        return e;
    }

    private Button button(String text) {
        Button b = new Button(this);
        b.setText(text); b.setAllCaps(false); b.setTextColor(Color.WHITE);
        b.setTextSize(15);
        GradientDrawable buttonBg = new GradientDrawable();
        buttonBg.setColor(Color.rgb(82, 136, 193));
        buttonBg.setCornerRadius(dp(10));
        b.setBackground(buttonBg);
        b.setPadding(dp(14), 0, dp(14), 0);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, dp(46));
        p.topMargin = dp(10);
        b.setLayoutParams(p);
        return b;
    }

    private void toast(String s) { Toast.makeText(this, s, Toast.LENGTH_LONG).show(); }
    private int dp(float v) { return (int)(v * getResources().getDisplayMetrics().density + 0.5f); }
}
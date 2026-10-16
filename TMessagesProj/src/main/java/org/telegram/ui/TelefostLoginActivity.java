package org.telegram.ui;

import android.app.Activity;
import android.os.Bundle;
import android.graphics.Color;
import android.graphics.Typeface;
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
        root.setPadding(dp(20), dp(24), dp(20), dp(16));
        root.setBackgroundColor(Color.rgb(13, 24, 42));
        setContentView(root);
        TextView brand = new TextView(this);
        brand.setText("FlostGram");
        brand.setTextColor(Color.WHITE);
        brand.setTextSize(30);
        brand.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        brand.setGravity(Gravity.CENTER);
        root.addView(brand, new LinearLayout.LayoutParams(-1, dp(58)));
        TextView subtitle = new TextView(this);
        subtitle.setText("Твой отдельный мессенджер");
        subtitle.setTextColor(Color.rgb(155, 185, 220));
        subtitle.setTextSize(14);
        subtitle.setGravity(Gravity.CENTER);
        root.addView(subtitle, new LinearLayout.LayoutParams(-1, dp(30)));
        ScrollView scroll = new ScrollView(this);
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(-1, 0, 1);
        sp.topMargin = dp(12);
        root.addView(scroll, sp);
        content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(content);
    }

    private void showLogin() {
        content.removeAllViews();
        title("Вход в FlostGram");
        note("Введи свой номер Telefost, выданный ботом. Код придёт от бота FlostGram, а не из Telegram.");
        phoneInput = input("Номер Telefost, например +79…", false);
        usernameInput = input("Юзернейм (например, user123)", false);
        nameInput = input("Как тебя называть", false);
        Button request = button("Получить код");
        content.addView(request);
        codeInput = input("Код из бота", false);
        Button verify = button("Войти / создать аккаунт");
        content.addView(verify);
        request.setOnClickListener(v -> {
            String phone = phoneInput.getText().toString().trim();
            if (phone.isEmpty()) { toast("Введи номер Telefost"); return; }
            request.setEnabled(false);
            api.requestCode(phone, new TelefostApi.Callback() {
                public void onSuccess(JSONObject result) {
                    request.setEnabled(true);
                    toast(result.optString("message", "Запрос отправлен. Проверь бота FlostGram."));
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
        currentPeer = "";
        title("Чаты Telefost");
        Button refresh = button("Обновить чаты");
        content.addView(refresh);
        searchInput = input("Найти по @юзернейму или номеру Telefost", false);
        Button search = button("Найти пользователя");
        content.addView(search);
        TextView results = note("Чаты и найденные пользователи появятся здесь.");
        content.addView(results);
        refresh.setOnClickListener(v -> api.getChats(new TelefostApi.Callback() {
            public void onSuccess(JSONObject data) {
                results.setText(formatChats(data));
                attachChatButtons(data, results);
            }
            public void onError(String message) { toast(message); }
        }));
        search.setOnClickListener(v -> {
            String q = searchInput.getText().toString().trim();
            if (q.isEmpty()) { toast("Введи @юзернейм или номер"); return; }
            api.searchUsers(q, new TelefostApi.Callback() {
                public void onSuccess(JSONObject data) {
                    results.setText(formatUsers(data));
                    attachUserButtons(data, results);
                }
                public void onError(String message) { toast(message); }
            });
        });
        Button logout = button("Выйти из Telefost");
        content.addView(logout);
        logout.setOnClickListener(v -> { api.signOut(); showLogin(); });
        refresh.performClick();
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
        for (int i=0;i<arr.length();i++) {
            JSONObject o = arr.optJSONObject(i);
            if (o == null) continue;
            String peer = o.optString("username", o.optString("peer", o.optString("phone", "")));
            if (peer.isEmpty()) continue;
            Button b = button("Открыть @" + peer);
            content.addView(b, Math.max(0, content.indexOfChild(results) + 1));
            b.setOnClickListener(v -> openChat(peer));
        }
    }

    private void attachUserButtons(JSONObject data, TextView results) {
        JSONArray arr = data.optJSONArray("users");
        if (arr == null) return;
        for (int i=0;i<arr.length();i++) {
            JSONObject o = arr.optJSONObject(i);
            if (o == null) continue;
            String peer = o.optString("username", o.optString("phone", ""));
            if (peer.isEmpty()) continue;
            Button b = button("Написать @" + peer);
            content.addView(b, Math.max(0, content.indexOfChild(results) + 1));
            b.setOnClickListener(v -> openChat(peer));
        }
    }

    private void title(String s) {
        TextView t = new TextView(this);
        t.setText(s); t.setTextColor(Color.WHITE); t.setTextSize(21);
        t.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, dp(48));
        p.topMargin = dp(12); content.addView(t, p);
    }

    private TextView note(String s) {
        TextView t = new TextView(this);
        t.setText(s); t.setTextColor(Color.rgb(220, 230, 242)); t.setTextSize(15);
        t.setPadding(dp(4), dp(10), dp(4), dp(10));
        return t;
    }

    private EditText input(String hint, boolean password) {
        EditText e = new EditText(this);
        e.setSingleLine(true); e.setHint(hint); e.setTextColor(Color.WHITE);
        e.setHintTextColor(Color.rgb(145, 165, 190));
        e.setPadding(dp(12), 0, dp(12), 0);
        e.setBackgroundTintList(android.content.res.ColorStateList.valueOf(Color.rgb(70, 130, 210)));
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, dp(52));
        p.topMargin = dp(8); content.addView(e, p);
        return e;
    }

    private Button button(String text) {
        Button b = new Button(this);
        b.setText(text); b.setAllCaps(false); b.setTextColor(Color.WHITE);
        b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(Color.rgb(37, 116, 210)));
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, dp(48));
        p.topMargin = dp(8);
        b.setLayoutParams(p);
        return b;
    }

    private void toast(String s) { Toast.makeText(this, s, Toast.LENGTH_LONG).show(); }
    private int dp(float v) { return (int)(v * getResources().getDisplayMetrics().density + 0.5f); }
}
package org.telegram.messenger;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Telefost's own-service API client.
 *
 * This talks only to Telefost's backend; it does not intercept or submit Telegram
 * account login codes and does not replace Telegram's MTProto transport.
 */
public final class TelefostApi {
    public static final String BASE_URL = "https://telefost-api.onrender.com";
    private static final String PREFS = "telefost_session";
    private static final String TOKEN_KEY = "access_token";
    private static final ExecutorService EXECUTOR = Executors.newFixedThreadPool(2);
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    public interface Callback {
        void onSuccess(JSONObject result);
        void onError(String message);
    }

    private final SharedPreferences preferences;

    public TelefostApi(Context context) {
        preferences = context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public boolean isSignedIn() {
        return !preferences.getString(TOKEN_KEY, "").isEmpty();
    }

    public void signOut() {
        preferences.edit().remove(TOKEN_KEY).apply();
    }

    public void requestCode(String phone, Callback callback) {
        JSONObject body = new JSONObject();
        try {
            body.put("phone", phone);
        } catch (JSONException e) {
            deliverError(callback, "Не удалось подготовить запрос.");
            return;
        }
        execute("POST", "/v1/auth/request-code", body, false, callback);
    }

    /** Verifies a code issued by Telefost and delivered by the Telefost bot. */
    public void verifyCode(String phone, String code, String username, String displayName, Callback callback) {
        JSONObject body = new JSONObject();
        try {
            body.put("phone", phone);
            body.put("code", code);
            body.put("username", username == null ? "" : username);
            body.put("display_name", displayName == null ? "" : displayName);
        } catch (JSONException e) {
            deliverError(callback, "Не удалось подготовить запрос.");
            return;
        }
        execute("POST", "/v1/auth/verify", body, false, new Callback() {
            @Override
            public void onSuccess(JSONObject result) {
                String token = result.optString("access_token", "");
                if (token.isEmpty()) {
                    callback.onError("Сервер не вернул токен сессии.");
                    return;
                }
                preferences.edit().putString(TOKEN_KEY, token).apply();
                callback.onSuccess(result);
            }

            @Override
            public void onError(String message) {
                callback.onError(message);
            }
        });
    }

    public void getMe(Callback callback) {
        execute("GET", "/v1/me", null, true, callback);
    }

    /** Search is restricted to an exact @username or Telefost phone number. */
    public void searchUsers(String usernameOrPhone, Callback callback) {
        try {
            String q = java.net.URLEncoder.encode(usernameOrPhone, "UTF-8");
            execute("GET", "/v1/users/search?q=" + q, null, true, callback);
        } catch (Exception e) {
            deliverError(callback, "Некорректный запрос поиска.");
        }
    }

    public void updateProfile(String username, String displayName, Callback callback) {
        JSONObject body = new JSONObject();
        try {
            body.put("username", username == null ? "" : username);
            body.put("display_name", displayName == null ? "" : displayName);
        } catch (JSONException e) {
            deliverError(callback, "Не удалось подготовить профиль.");
            return;
        }
        execute("PATCH", "/v1/me", body, true, callback);
    }

    public void createRequest(String kind, String item, String recipient, Callback callback) {
        JSONObject body = new JSONObject();
        try {
            body.put("kind", kind);
            body.put("item", item);
            body.put("recipient", recipient == null ? "" : recipient);
        } catch (JSONException e) {
            deliverError(callback, "Не удалось подготовить заявку.");
            return;
        }
        execute("POST", "/v1/requests", body, true, callback);
    }

    /** List recent Telefost conversations for the signed-in account. */
    public void getChats(Callback callback) {
        execute("GET", "/v1/chats", null, true, callback);
    }

    /** Fetch message history with an exact @username or Telefost number. */
    public void getChat(String usernameOrPhone, Callback callback) {
        try {
            String peer = java.net.URLEncoder.encode(usernameOrPhone, "UTF-8").replace("+", "%20");
            execute("GET", "/v1/chats/" + peer, null, true, callback);
        } catch (Exception e) {
            deliverError(callback, "Некорректный адрес чата.");
        }
    }

    /** Send a plain-text message through Telefost's own backend. */
    public void sendMessage(String usernameOrPhone, String text, Callback callback) {
        JSONObject body = new JSONObject();
        try {
            body.put("text", text == null ? "" : text);
            String peer = java.net.URLEncoder.encode(usernameOrPhone, "UTF-8").replace("+", "%20");
            execute("POST", "/v1/chats/" + peer + "/messages", body, true, callback);
        } catch (Exception e) {
            deliverError(callback, "Не удалось подготовить сообщение.");
        }
    }

    private void execute(String method, String path, JSONObject body, boolean authenticated, Callback callback) {
        EXECUTOR.execute(() -> {
            HttpURLConnection connection = null;
            try {
                URL url = new URL(BASE_URL + path);
                connection = (HttpURLConnection) url.openConnection();
                connection.setRequestMethod(method);
                connection.setConnectTimeout(12000);
                connection.setReadTimeout(15000);
                connection.setRequestProperty("Accept", "application/json");
                if (body != null) {
                    connection.setDoOutput(true);
                    connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                }
                if (authenticated) {
                    String token = preferences.getString(TOKEN_KEY, "");
                    if (token.isEmpty()) {
                        deliverError(callback, "Сначала войди в аккаунт Telefost.");
                        return;
                    }
                    connection.setRequestProperty("Authorization", "Bearer " + token);
                }
                if (body != null) {
                    byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                    try (OutputStream out = connection.getOutputStream()) {
                        out.write(bytes);
                    }
                }
                int status = connection.getResponseCode();
                InputStream stream = status >= 200 && status < 300
                        ? connection.getInputStream() : connection.getErrorStream();
                String response = readAll(stream);
                JSONObject json = response.isEmpty() ? new JSONObject() : new JSONObject(response);
                if (status >= 200 && status < 300) {
                    MAIN.post(() -> callback.onSuccess(json));
                } else {
                    String message = json.optString("detail", "Ошибка сервера Telefost (" + status + ").");
                    deliverError(callback, message);
                }
            } catch (Exception e) {
                deliverError(callback, "Не удалось подключиться к Telefost. Проверь интернет и доступность сервера.");
            } finally {
                if (connection != null) connection.disconnect();
            }
        });
    }

    private static String readAll(InputStream stream) throws Exception {
        if (stream == null) return "";
        StringBuilder result = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) result.append(line);
        }
        return result.toString();
    }

    private static void deliverError(Callback callback, String message) {
        MAIN.post(() -> callback.onError(message));
    }
}

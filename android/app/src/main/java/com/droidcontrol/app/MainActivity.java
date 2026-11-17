
package com.droidcontrol.app;

import android.app.Activity;
import android.os.Bundle;
import android.os.Build;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Color;
import android.view.Gravity;
import android.widget.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.io.BufferedReader;
import java.io.InputStreamReader;

public class MainActivity extends Activity {

    TextView status, deviceInfo, batteryInfo;

    private static final String SERVER =
        "http://127.0.0.1:5000/api/health";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(35, 45, 35, 35);
        layout.setBackgroundColor(Color.rgb(20, 24, 32));

        TextView title = new TextView(this);
        title.setText("DROIDCONTROL");
        title.setTextSize(28);
        title.setTextColor(Color.GREEN);
        title.setGravity(Gravity.CENTER);

        TextView subtitle = new TextView(this);
        subtitle.setText("Android Client v0.2");
        subtitle.setTextColor(Color.WHITE);
        subtitle.setGravity(Gravity.CENTER);

        deviceInfo = new TextView(this);
        deviceInfo.setTextColor(Color.WHITE);
        deviceInfo.setTextSize(17);
        deviceInfo.setPadding(0, 35, 0, 15);

        batteryInfo = new TextView(this);
        batteryInfo.setTextColor(Color.GREEN);
        batteryInfo.setTextSize(17);

        status = new TextView(this);
        status.setText("Server: Not tested");
        status.setTextColor(Color.YELLOW);
        status.setPadding(0, 25, 0, 25);

        Button testButton = new Button(this);
        testButton.setText("TEST SERVER CONNECTION");

        testButton.setOnClickListener(v -> {
            status.setText("Checking server...");
            testButton.setEnabled(false);

            new Thread(() -> {
                String result = "Server connection failed";

                try {
                    HttpURLConnection connection =
                        (HttpURLConnection)
                        new URL(SERVER).openConnection();

                    connection.setRequestMethod("GET");
                    connection.setConnectTimeout(5000);
                    connection.setReadTimeout(5000);

                    int response = connection.getResponseCode();

                    if (response == 200) {
                        BufferedReader reader =
                            new BufferedReader(
                                new InputStreamReader(
                                    connection.getInputStream()
                                )
                            );

                        String responseBody = reader.readLine();
                        reader.close();

                        if (responseBody != null &&
                            responseBody.contains("\"online\"")) {
                            result = "SERVER ONLINE";
                        } else {
                            result = "Unexpected server response";
                        }
                    } else {
                        result = "HTTP Error: " + response;
                    }

                    connection.disconnect();

                } catch (Exception e) {
                    result = "Connection failed: " +
                        e.getClass().getSimpleName();
                }

                final String message = result;

                runOnUiThread(() -> {
                    status.setText(message);
                    status.setTextColor(
                        message.equals("SERVER ONLINE")
                        ? Color.GREEN : Color.RED
                    );
                    testButton.setEnabled(true);
                });

            }).start();
        });

        deviceInfo.setText(
            "Manufacturer: " + Build.MANUFACTURER +
            "\nModel: " + Build.MODEL +
            "\nAndroid: " + Build.VERSION.RELEASE
        );

        Intent battery = registerReceiver(
            null,
            new IntentFilter(Intent.ACTION_BATTERY_CHANGED)
        );

        if (battery != null) {
            int level = battery.getIntExtra("level", -1);
            batteryInfo.setText("Battery: " + level + "%");
        }

        layout.addView(title);
        layout.addView(subtitle);
        layout.addView(deviceInfo);
        layout.addView(batteryInfo);
        layout.addView(status);
        layout.addView(testButton);

        setContentView(layout);
    }
}

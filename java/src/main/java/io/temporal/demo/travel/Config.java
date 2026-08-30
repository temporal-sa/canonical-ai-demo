package io.temporal.demo.travel;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

public record Config(
    String taskQueue,
    String temporalAddress,
    String temporalNamespace,
    String temporalApiKey,
    String temporalTlsCert,
    String temporalTlsKey,
    String dbUrl,
    String llmProvider,
    String anthropicApiKey,
    String anthropicModel,
    int researchSearches,
    int webSearchMaxUses,
    double webSearchFailRate,
    boolean checkoutFailHotel,
    Duration checkoutStepDelay,
    Duration toolDelay,
    String anthropicMessagesUrl,
    Map<String, String> envValues) {

  public static Config load() {
    Map<String, String> values = new HashMap<>();
    loadDotEnv(Path.of("../.env"), values);
    loadDotEnv(Path.of(".env"), values);
    values.putAll(System.getenv());
    String taskQueue = first(values, List.of("TEMPORAL_TASK_QUEUE", "TASK_QUEUE"), "travel-agent");
    return new Config(
        taskQueue,
        get(values, "TEMPORAL_ADDRESS", "localhost:7233"),
        get(values, "TEMPORAL_NAMESPACE", "default"),
        get(values, "TEMPORAL_API_KEY", ""),
        get(values, "TEMPORAL_TLS_CERT", ""),
        get(values, "TEMPORAL_TLS_KEY", ""),
        databaseUrl(values),
        get(values, "LLM_PROVIDER", "anthropic"),
        get(values, "ANTHROPIC_API_KEY", ""),
        get(values, "ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        integer(values, "RESEARCH_SEARCHES", 6),
        integer(values, "WEB_SEARCH_MAX_USES", 1),
        decimal(values, "WEB_SEARCH_FAIL_RATE", 0.4),
        bool(values, "CHECKOUT_FAIL_HOTEL", true),
        seconds(values, "CHECKOUT_STEP_DELAY_SECONDS", 1.0),
        seconds(values, "TOOL_DELAY_SECONDS", 1.0),
        get(values, "ANTHROPIC_MESSAGES_URL", "https://api.anthropic.com/v1/messages"),
        values
    );
  }

  private static void loadDotEnv(Path path, Map<String, String> values) {
    if (!Files.isRegularFile(path)) return;
    try {
      for (String raw : Files.readAllLines(path)) {
        String line = raw.trim();
        if (line.isEmpty() || line.startsWith("#") || !line.contains("=")) continue;
        int split = line.indexOf('=');
        String key = line.substring(0, split).trim();
        String value = line.substring(split + 1).trim();
        if (value.length() >= 2 && value.startsWith("\"") && value.endsWith("\"")) {
          value = value.substring(1, value.length() - 1);
        }
        values.put(key, value);
      }
    } catch (IOException ignored) {
      // Environment variables and defaults still make the worker configurable.
    }
  }

  private static String databaseUrl(Map<String, String> values) {
    String direct = values.get("DB_URL");
    if (direct != null && !direct.isBlank()) return direct;
    String host = values.get("DB_HOST");
    if (host == null || host.isBlank()) return "postgresql://demo:demo@localhost:5432/travel";
    return "postgresql://%s:%s@%s:%s/%s".formatted(
        get(values, "DB_USER", "demo"), get(values, "DB_PASSWORD", "demo"), host,
        get(values, "DB_PORT", "5432"), get(values, "DB_NAME", "travel"));
  }

  private static String first(Map<String, String> values, List<String> keys, String fallback) {
    for (String key : keys) {
      String value = values.get(key);
      if (value != null && !value.isBlank()) return value;
    }
    return fallback;
  }

  private static String get(Map<String, String> values, String key, String fallback) {
    String value = values.get(key);
    return value == null || value.isBlank() ? fallback : value;
  }

  private static int integer(Map<String, String> values, String key, int fallback) {
    try { return Integer.parseInt(get(values, key, Integer.toString(fallback))); }
    catch (NumberFormatException ignored) { return fallback; }
  }

  private static double decimal(Map<String, String> values, String key, double fallback) {
    try { return Double.parseDouble(get(values, key, Double.toString(fallback))); }
    catch (NumberFormatException ignored) { return fallback; }
  }

  private static boolean bool(Map<String, String> values, String key, boolean fallback) {
    String value = values.get(key);
    if (value == null || value.isBlank()) return fallback;
    return switch (value.toLowerCase(Locale.ROOT)) {
      case "1", "true", "yes", "on" -> true;
      case "0", "false", "no", "off" -> false;
      default -> fallback;
    };
  }

  private static Duration seconds(Map<String, String> values, String key, double fallback) {
    return Duration.ofMillis(Math.max(0L, Math.round(decimal(values, key, fallback) * 1000)));
  }
}

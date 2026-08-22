package io.temporal.demo.travel;

import io.temporal.demo.travel.Models.ItineraryItem;
import java.math.BigDecimal;
import java.net.URI;
import java.sql.Connection;
import java.sql.Date;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.LocalDate;
import java.time.Month;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

final class Database {
  static final class BusinessException extends RuntimeException {
    BusinessException(String message) { super(message); }
  }

  private final String jdbcUrl;
  private final String user;
  private final String password;

  Database(String databaseUrl) {
    URI uri = URI.create(databaseUrl);
    String[] credentials = uri.getUserInfo() == null ? new String[] {"demo", "demo"} : uri.getUserInfo().split(":", 2);
    user = credentials[0];
    password = credentials.length > 1 ? credentials[1] : "";
    int port = uri.getPort() < 0 ? 5432 : uri.getPort();
    jdbcUrl = "jdbc:postgresql://%s:%d%s".formatted(uri.getHost(), port, uri.getPath());
  }

  List<Map<String, Object>> searchDestinations(String query) {
    return query("""
        SELECT destination_id, city, country, region, airport_code,
               summary, best_season, avg_daily_budget, tags
        FROM destination
        WHERE city ILIKE ? OR country ILIKE ? OR region ILIKE ? OR tags ILIKE ? OR summary ILIKE ?
        ORDER BY city LIMIT 15
        """, repeat("%" + query + "%", 5));
  }

  Map<String, Object> getDestinationInfo(String name) {
    List<Map<String, Object>> rows = query("""
        SELECT destination_id, city, country, region, airport_code,
               summary, best_season, avg_daily_budget, tags
        FROM destination WHERE city ILIKE ? OR country ILIKE ? ORDER BY city LIMIT 1
        """, List.of("%" + name + "%", "%" + name + "%"));
    if (rows.isEmpty()) return Map.of("error", "No destination found matching '%s'.".formatted(name));
    Map<String, Object> destination = new LinkedHashMap<>(rows.get(0));
    destination.put("attractions", query("""
        SELECT attraction_id, name, category, description,
               typical_cost::float8 AS typical_cost, duration_hours::float8 AS duration_hours
        FROM attraction WHERE destination_id = ? ORDER BY attraction_id
        """, List.of(destination.get("destination_id"))));
    return destination;
  }

  List<Map<String, Object>> searchFlights(String destination, String origin, String departDate) {
    StringBuilder sql = new StringBuilder("""
        SELECT flight_id, airline, flight_no, origin_city, origin_code, dest_city, dest_code,
               depart_time, arrive_time, duration_min, stops, price::float8 AS price, cabin
        FROM flight WHERE (dest_city ILIKE ? OR dest_code ILIKE ?)
        """);
    List<Object> params = new ArrayList<>(List.of("%" + destination + "%", destination));
    if (origin != null && !origin.isBlank()) {
      sql.append(" AND (origin_city ILIKE ? OR origin_code ILIKE ?)");
      params.add("%" + origin + "%");
      params.add(origin);
    }
    sql.append(" ORDER BY price LIMIT 12");
    List<Map<String, Object>> rows = query(sql.toString(), params);
    String effectiveDate = departDate == null || departDate.isBlank() ? defaultFlightDate() : departDate;
    rows.forEach(row -> row.put("depart_date", effectiveDate));
    return rows;
  }

  List<Map<String, Object>> searchEvents(String destination, Object month) {
    StringBuilder sql = new StringBuilder("""
        SELECT e.event_id, e.name, e.category, e.start_date::text AS start_date,
               e.end_date::text AS end_date, e.description, d.city, d.country
        FROM event e JOIN destination d ON d.destination_id = e.destination_id
        WHERE (d.city ILIKE ? OR d.country ILIKE ?)
        """);
    List<Object> params = new ArrayList<>(List.of("%" + destination + "%", "%" + destination + "%"));
    int monthNumber = monthNumber(month);
    if (monthNumber > 0) {
      sql.append(" AND (EXTRACT(MONTH FROM e.start_date) = ? OR EXTRACT(MONTH FROM e.end_date) = ?)");
      params.add(monthNumber);
      params.add(monthNumber);
    }
    sql.append(" ORDER BY e.start_date LIMIT 12");
    List<Map<String, Object>> rows = query(sql.toString(), params);
    for (Map<String, Object> row : rows) {
      String[] dates = rebaseEventDates(text(row.get("start_date")), text(row.get("end_date")));
      row.put("start_date", dates[0]);
      row.put("end_date", dates[1]);
    }
    rows.sort((a, b) -> text(a.get("start_date")).compareTo(text(b.get("start_date"))));
    return rows;
  }

  List<Map<String, Object>> searchHotels(String destination, Double maxPrice) {
    StringBuilder sql = new StringBuilder("""
        SELECT h.hotel_id, h.name, h.area, h.stars, h.rating::float8 AS rating,
               h.nightly_price::float8 AS nightly_price, d.city
        FROM hotel h JOIN destination d ON d.destination_id = h.destination_id
        WHERE (d.city ILIKE ? OR d.country ILIKE ?)
        """);
    List<Object> params = new ArrayList<>(List.of("%" + destination + "%", "%" + destination + "%"));
    if (maxPrice != null) {
      sql.append(" AND h.nightly_price <= ?");
      params.add(maxPrice);
    }
    sql.append(" ORDER BY h.nightly_price LIMIT 12");
    return query(sql.toString(), params);
  }

  List<Map<String, Object>> searchAttractions(String destination) {
    return query("""
        SELECT a.attraction_id, a.name, a.category, a.description,
               a.typical_cost::float8 AS typical_cost, a.duration_hours::float8 AS duration_hours, d.city
        FROM attraction a JOIN destination d ON d.destination_id = a.destination_id
        WHERE d.city ILIKE ? OR d.country ILIKE ? ORDER BY a.attraction_id LIMIT 20
        """, List.of("%" + destination + "%", "%" + destination + "%"));
  }

  List<ItineraryItem> getItineraryItems(List<Map<String, Object>> items) {
    List<ItineraryItem> result = new ArrayList<>();
    for (Map<String, Object> item : items) {
      String kind = text(item.get("kind"));
      long id = whole(item.get("id"));
      List<Map<String, Object>> rows;
      switch (kind) {
        case "flight" -> {
          rows = query("""
              SELECT flight_id, airline, flight_no, origin_city, dest_city, depart_time,
                     price::float8 AS price FROM flight WHERE flight_id = ?
              """, List.of(id));
          if (!rows.isEmpty()) {
            Map<String, Object> r = rows.get(0);
            result.add(new ItineraryItem("flight", whole(r.get("flight_id")), text(r.get("airline")) + " " + text(r.get("flight_no")),
                "%s → %s · %s %s".formatted(r.get("origin_city"), r.get("dest_city"), defaultFlightDate(), r.get("depart_time")), decimal(r.get("price"))));
          }
        }
        case "hotel" -> {
          rows = query("""
              SELECT h.hotel_id, h.name, h.area, h.stars, h.nightly_price::float8 AS price, d.city
              FROM hotel h JOIN destination d ON d.destination_id = h.destination_id WHERE h.hotel_id = ?
              """, List.of(id));
          if (!rows.isEmpty()) {
            Map<String, Object> r = rows.get(0);
            result.add(new ItineraryItem("hotel", whole(r.get("hotel_id")), text(r.get("name")),
                "%s, %s · %s★ · $%.0f/night".formatted(r.get("area"), r.get("city"), r.get("stars"), decimal(r.get("price"))), decimal(r.get("price"))));
          }
        }
        case "activity" -> {
          rows = query("""
              SELECT a.attraction_id, a.name, a.category, a.typical_cost::float8 AS price, d.city
              FROM attraction a JOIN destination d ON d.destination_id = a.destination_id WHERE a.attraction_id = ?
              """, List.of(id));
          if (!rows.isEmpty()) {
            Map<String, Object> r = rows.get(0);
            result.add(new ItineraryItem("activity", whole(r.get("attraction_id")), text(r.get("name")),
                "%s · %s".formatted(r.get("category"), r.get("city")), decimal(r.get("price"))));
          }
        }
        default -> { }
      }
    }
    return result;
  }

  List<Map<String, Object>> getBookings(String accountKey) {
    return query("""
        SELECT b.booking_id, b.created_at::date::text AS date, b.total::float8 AS total,
               b.summary, count(l.booking_line_id)::int AS item_count
        FROM booking b LEFT JOIN booking_line l ON l.booking_id = b.booking_id
        WHERE b.account_key = ? GROUP BY b.booking_id, b.created_at, b.total, b.summary
        ORDER BY b.created_at DESC, b.booking_id DESC LIMIT 10
        """, List.of(accountKey));
  }

  List<Map<String, Object>> getBookingDetails(long bookingId) {
    return query("SELECT kind, ref_id, title, price::float8 AS price FROM booking_line WHERE booking_id = ? ORDER BY booking_line_id", List.of(bookingId));
  }

  List<Map<String, Object>> itemsAlreadyBooked(String accountKey, List<ItineraryItem> items) {
    if (items.isEmpty()) return List.of();
    StringBuilder sql = new StringBuilder("""
        SELECT DISTINCT l.kind, l.ref_id, l.title FROM booking_line l
        JOIN booking b ON b.booking_id = l.booking_id WHERE b.account_key = ? AND (
        """);
    List<Object> params = new ArrayList<>();
    params.add(accountKey);
    for (int i = 0; i < items.size(); i++) {
      if (i > 0) sql.append(" OR ");
      sql.append("(l.kind = ? AND l.ref_id = ?)");
      params.add(items.get(i).kind());
      params.add(items.get(i).ref_id());
    }
    sql.append(") ORDER BY l.kind, l.ref_id");
    return query(sql.toString(), params);
  }

  Map<String, Object> recordInvoice(String accountKey, double amount, String flightDetails) {
    try (Connection connection = connect()) {
      connection.setAutoCommit(false);
      try {
        long id = scalar(connection, "SELECT coalesce(max(invoice_id), 0) + 1 FROM invoice");
        execute(connection, "INSERT INTO invoice (invoice_id, account_key, created_at, amount, flight_details) VALUES (?, ?, now(), ?, ?)", List.of(id, accountKey, amount, flightDetails));
        connection.commit();
        return Map.of("invoice_id", id, "amount", amount, "flight_details", flightDetails, "status", "invoiced");
      } catch (Exception error) {
        connection.rollback();
        throw error;
      }
    } catch (SQLException error) {
      throw new RuntimeException(error);
    }
  }

  Map<String, Object> recordBooking(String accountKey, List<ItineraryItem> items, String summary) {
    if (items.isEmpty()) throw new BusinessException("Nothing to book — the itinerary is empty.");
    double total = round2(items.stream().mapToDouble(ItineraryItem::price).sum());
    try (Connection connection = connect()) {
      connection.setAutoCommit(false);
      try {
        long bookingId = scalar(connection, "SELECT coalesce(max(booking_id), 0) + 1 FROM booking");
        long lineId = scalar(connection, "SELECT coalesce(max(booking_line_id), 0) FROM booking_line");
        execute(connection, "INSERT INTO booking (booking_id, account_key, created_at, total, summary) VALUES (?, ?, now(), ?, ?)", List.of(bookingId, accountKey, total, summary));
        for (ItineraryItem item : items) {
          execute(connection, "INSERT INTO booking_line (booking_line_id, booking_id, kind, ref_id, title, price) VALUES (?, ?, ?, ?, ?, ?)",
              List.of(++lineId, bookingId, item.kind(), item.ref_id(), item.title(), item.price()));
        }
        connection.commit();
        return Map.of("booking_id", bookingId, "items", items, "total", total);
      } catch (Exception error) {
        connection.rollback();
        throw error;
      }
    } catch (SQLException error) {
      throw new RuntimeException(error);
    }
  }

  private Connection connect() throws SQLException { return DriverManager.getConnection(jdbcUrl, user, password); }

  private List<Map<String, Object>> query(String sql, List<?> params) {
    try (Connection connection = connect(); PreparedStatement statement = connection.prepareStatement(sql)) {
      bind(statement, params);
      try (ResultSet rs = statement.executeQuery()) {
        ResultSetMetaData metadata = rs.getMetaData();
        List<Map<String, Object>> result = new ArrayList<>();
        while (rs.next()) {
          Map<String, Object> row = new LinkedHashMap<>();
          for (int i = 1; i <= metadata.getColumnCount(); i++) row.put(metadata.getColumnLabel(i), normalize(rs.getObject(i)));
          result.add(row);
        }
        return result;
      }
    } catch (SQLException error) {
      throw new RuntimeException(error);
    }
  }

  private static void execute(Connection connection, String sql, List<?> params) throws SQLException {
    try (PreparedStatement statement = connection.prepareStatement(sql)) {
      bind(statement, params);
      statement.executeUpdate();
    }
  }

  private static long scalar(Connection connection, String sql) throws SQLException {
    try (PreparedStatement statement = connection.prepareStatement(sql); ResultSet rs = statement.executeQuery()) {
      rs.next();
      return rs.getLong(1);
    }
  }

  private static void bind(PreparedStatement statement, List<?> params) throws SQLException {
    for (int i = 0; i < params.size(); i++) statement.setObject(i + 1, params.get(i));
  }

  private static Object normalize(Object value) {
    if (value instanceof BigDecimal decimal) return decimal.doubleValue();
    if (value instanceof Date date) return date.toLocalDate().toString();
    if (value instanceof Timestamp timestamp) return timestamp.toInstant().toString();
    return value;
  }

  private static List<Object> repeat(Object value, int count) {
    List<Object> result = new ArrayList<>();
    for (int i = 0; i < count; i++) result.add(value);
    return result;
  }

  private static String defaultFlightDate() { return LocalDate.now().plusDays(21).toString(); }

  private static int monthNumber(Object value) {
    if (value == null || text(value).isBlank()) return 0;
    String input = text(value).trim().toLowerCase(Locale.ROOT);
    try { return Month.valueOf(input.toUpperCase(Locale.ROOT)).getValue(); }
    catch (IllegalArgumentException ignored) { }
    if (input.length() >= 3) {
      for (Month month : Month.values()) if (month.name().toLowerCase(Locale.ROOT).startsWith(input.substring(0, 3))) return month.getValue();
    }
    String[] parts = input.split("-");
    try {
      int parsed = Integer.parseInt(parts.length >= 2 ? parts[1] : parts[0]);
      return parsed >= 1 && parsed <= 12 ? parsed : 0;
    } catch (NumberFormatException ignored) { return 0; }
  }

  private static String[] rebaseEventDates(String startIso, String endIso) {
    try {
      LocalDate start = LocalDate.parse(startIso);
      LocalDate end = LocalDate.parse(endIso);
      LocalDate today = LocalDate.now();
      int year = LocalDate.of(today.getYear(), start.getMonth(), Math.min(start.getDayOfMonth(), start.getMonth().length(today.isLeapYear()))).isBefore(today) ? today.getYear() + 1 : today.getYear();
      int delta = year - start.getYear();
      return new String[] {start.plusYears(delta).toString(), end.plusYears(delta).toString()};
    } catch (DateTimeParseException error) {
      return new String[] {startIso, endIso};
    }
  }

  static String text(Object value) { return value == null ? "" : String.valueOf(value); }
  static double decimal(Object value) { return value instanceof Number n ? n.doubleValue() : Double.parseDouble(text(value)); }
  static long whole(Object value) { return value instanceof Number n ? n.longValue() : Long.parseLong(text(value)); }
  static double round2(double value) { return Math.round(value * 100.0) / 100.0; }
}

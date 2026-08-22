package travelagent

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type BusinessError struct{ Message string }

func (e *BusinessError) Error() string { return e.Message }

type DB struct{ pool *pgxpool.Pool }

func NewDB(ctx context.Context, databaseURL string) (*DB, error) {
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		return nil, fmt.Errorf("create database pool: %w", err)
	}
	return &DB{pool: pool}, nil
}

func (d *DB) Close() { d.pool.Close() }

func (d *DB) query(ctx context.Context, sql string, args ...any) ([]map[string]any, error) {
	rows, err := d.pool.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	fields := rows.FieldDescriptions()
	result := make([]map[string]any, 0)
	for rows.Next() {
		values, err := rows.Values()
		if err != nil {
			return nil, err
		}
		row := make(map[string]any, len(values))
		for i, value := range values {
			if bytes, ok := value.([]byte); ok {
				value = string(bytes)
			}
			row[string(fields[i].Name)] = value
		}
		result = append(result, row)
	}
	return result, rows.Err()
}

func (d *DB) SearchDestinations(ctx context.Context, query string) ([]map[string]any, error) {
	return d.query(ctx, `
        SELECT destination_id, city, country, region, airport_code,
               summary, best_season, avg_daily_budget, tags
        FROM destination
        WHERE city ILIKE $1 OR country ILIKE $1 OR region ILIKE $1
           OR tags ILIKE $1 OR summary ILIKE $1
        ORDER BY city
        LIMIT 15`, "%"+query+"%")
}

func (d *DB) GetDestinationInfo(ctx context.Context, name string) (map[string]any, error) {
	destinations, err := d.query(ctx, `
        SELECT destination_id, city, country, region, airport_code,
               summary, best_season, avg_daily_budget, tags
        FROM destination
        WHERE city ILIKE $1 OR country ILIKE $1
        ORDER BY city LIMIT 1`, "%"+name+"%")
	if err != nil {
		return nil, err
	}
	if len(destinations) == 0 {
		return map[string]any{"error": fmt.Sprintf("No destination found matching '%s'.", name)}, nil
	}
	destination := destinations[0]
	attractions, err := d.query(ctx, `
        SELECT attraction_id, name, category, description,
               typical_cost::float8 AS typical_cost, duration_hours::float8 AS duration_hours
        FROM attraction WHERE destination_id = $1
        ORDER BY attraction_id`, destination["destination_id"])
	if err != nil {
		return nil, err
	}
	destination["attractions"] = attractions
	return destination, nil
}

func (d *DB) SearchFlights(ctx context.Context, destination, origin, departDate string) ([]map[string]any, error) {
	clause := "(dest_city ILIKE $1 OR dest_code ILIKE $2)"
	args := []any{"%" + destination + "%", destination}
	if origin != "" {
		clause += " AND (origin_city ILIKE $3 OR origin_code ILIKE $4)"
		args = append(args, "%"+origin+"%", origin)
	}
	rows, err := d.query(ctx, `
        SELECT flight_id, airline, flight_no, origin_city, origin_code,
               dest_city, dest_code, depart_time::text AS depart_time,
               arrive_time::text AS arrive_time, duration_min,
               stops, price::float8 AS price, cabin
        FROM flight
        WHERE `+clause+`
        ORDER BY price
        LIMIT 12`, args...)
	if err != nil {
		return nil, err
	}
	if departDate == "" {
		departDate = defaultFlightDate(time.Now())
	}
	for _, row := range rows {
		row["depart_date"] = departDate
	}
	return rows, nil
}

func (d *DB) SearchEvents(ctx context.Context, destination string, month any) ([]map[string]any, error) {
	clause := "(d.city ILIKE $1 OR d.country ILIKE $1)"
	args := []any{"%" + destination + "%"}
	if number := monthNumber(month); number != 0 {
		clause += " AND (EXTRACT(MONTH FROM e.start_date) = $2 OR EXTRACT(MONTH FROM e.end_date) = $2)"
		args = append(args, number)
	}
	rows, err := d.query(ctx, `
        SELECT e.event_id, e.name, e.category,
               e.start_date::text AS start_date, e.end_date::text AS end_date,
               e.description, d.city, d.country
        FROM event e
        JOIN destination d ON d.destination_id = e.destination_id
        WHERE `+clause+`
        ORDER BY e.start_date
        LIMIT 12`, args...)
	if err != nil {
		return nil, err
	}
	now := time.Now()
	for _, row := range rows {
		start, end := rebaseEventDates(stringValue(row["start_date"]), stringValue(row["end_date"]), now)
		row["start_date"], row["end_date"] = start, end
	}
	sort.SliceStable(rows, func(i, j int) bool {
		return stringValue(rows[i]["start_date"]) < stringValue(rows[j]["start_date"])
	})
	return rows, nil
}

func (d *DB) SearchHotels(ctx context.Context, destination string, maxPrice *float64) ([]map[string]any, error) {
	clause := "(d.city ILIKE $1 OR d.country ILIKE $1)"
	args := []any{"%" + destination + "%"}
	if maxPrice != nil {
		clause += " AND h.nightly_price <= $2"
		args = append(args, *maxPrice)
	}
	return d.query(ctx, `
        SELECT h.hotel_id, h.name, h.area, h.stars, h.rating::float8 AS rating,
               h.nightly_price::float8 AS nightly_price, d.city
        FROM hotel h
        JOIN destination d ON d.destination_id = h.destination_id
        WHERE `+clause+`
        ORDER BY h.nightly_price
        LIMIT 12`, args...)
}

func (d *DB) SearchAttractions(ctx context.Context, destination string) ([]map[string]any, error) {
	return d.query(ctx, `
        SELECT a.attraction_id, a.name, a.category, a.description,
               a.typical_cost::float8 AS typical_cost,
               a.duration_hours::float8 AS duration_hours, d.city
        FROM attraction a
        JOIN destination d ON d.destination_id = a.destination_id
        WHERE d.city ILIKE $1 OR d.country ILIKE $1
        ORDER BY a.attraction_id
        LIMIT 20`, "%"+destination+"%")
}

func (d *DB) GetItineraryItems(ctx context.Context, items []map[string]any) ([]ItineraryItem, error) {
	result := make([]ItineraryItem, 0, len(items))
	for _, item := range items {
		kind := stringValue(item["kind"])
		refID := int64Value(item["id"])
		if kind == "" || refID == 0 {
			continue
		}
		var rows []map[string]any
		var err error
		switch kind {
		case "flight":
			rows, err = d.query(ctx, `
                SELECT flight_id, airline, flight_no, origin_city, dest_city,
                       depart_time::text AS depart_time, price::float8 AS price
                FROM flight WHERE flight_id = $1`, refID)
			if err == nil && len(rows) > 0 {
				r := rows[0]
				result = append(result, ItineraryItem{
					Kind: "flight", RefID: int64Value(r["flight_id"]),
					Title:    stringValue(r["airline"]) + " " + stringValue(r["flight_no"]),
					Subtitle: fmt.Sprintf("%s → %s · %s %s", r["origin_city"], r["dest_city"], defaultFlightDate(time.Now()), r["depart_time"]),
					Price:    floatValue(r["price"]),
				})
			}
		case "hotel":
			rows, err = d.query(ctx, `
                SELECT h.hotel_id, h.name, h.area, h.stars,
                       h.nightly_price::float8 AS price, d.city
                FROM hotel h JOIN destination d ON d.destination_id = h.destination_id
                WHERE h.hotel_id = $1`, refID)
			if err == nil && len(rows) > 0 {
				r := rows[0]
				result = append(result, ItineraryItem{
					Kind: "hotel", RefID: int64Value(r["hotel_id"]), Title: stringValue(r["name"]),
					Subtitle: fmt.Sprintf("%s, %s · %v★ · $%.0f/night", r["area"], r["city"], r["stars"], floatValue(r["price"])),
					Price:    floatValue(r["price"]),
				})
			}
		case "activity":
			rows, err = d.query(ctx, `
                SELECT a.attraction_id, a.name, a.category,
                       a.typical_cost::float8 AS price, d.city
                FROM attraction a JOIN destination d ON d.destination_id = a.destination_id
                WHERE a.attraction_id = $1`, refID)
			if err == nil && len(rows) > 0 {
				r := rows[0]
				result = append(result, ItineraryItem{
					Kind: "activity", RefID: int64Value(r["attraction_id"]), Title: stringValue(r["name"]),
					Subtitle: fmt.Sprintf("%s · %s", r["category"], r["city"]), Price: floatValue(r["price"]),
				})
			}
		}
		if err != nil {
			return nil, err
		}
	}
	return result, nil
}

func (d *DB) GetBookings(ctx context.Context, accountKey string) ([]map[string]any, error) {
	return d.query(ctx, `
        SELECT b.booking_id, b.created_at::date::text AS date,
               b.total::float8 AS total, b.summary,
               count(l.booking_line_id)::int AS item_count
        FROM booking b
        LEFT JOIN booking_line l ON l.booking_id = b.booking_id
        WHERE b.account_key = $1
        GROUP BY b.booking_id, b.created_at, b.total, b.summary
        ORDER BY b.created_at DESC, b.booking_id DESC
        LIMIT 10`, accountKey)
}

func (d *DB) GetBookingDetails(ctx context.Context, bookingID int64) ([]map[string]any, error) {
	return d.query(ctx, `
        SELECT kind, ref_id, title, price::float8 AS price
        FROM booking_line WHERE booking_id = $1
        ORDER BY booking_line_id`, bookingID)
}

func (d *DB) ItemsAlreadyBooked(ctx context.Context, accountKey string, items []ItineraryItem) ([]map[string]any, error) {
	if len(items) == 0 {
		return []map[string]any{}, nil
	}
	kinds := make([]string, len(items))
	refs := make([]int64, len(items))
	for i, item := range items {
		kinds[i], refs[i] = item.Kind, item.RefID
	}
	return d.query(ctx, `
        SELECT DISTINCT l.kind, l.ref_id, l.title
        FROM booking_line l
        JOIN booking b ON b.booking_id = l.booking_id
        WHERE b.account_key = $1
          AND (l.kind, l.ref_id) IN (SELECT kind, ref_id FROM unnest(
                $2::text[], $3::bigint[]) AS t(kind, ref_id))
        ORDER BY l.kind, l.ref_id`, accountKey, kinds, refs)
}

func (d *DB) RecordInvoice(ctx context.Context, accountKey string, amount float64, flightDetails string) (map[string]any, error) {
	tx, err := d.pool.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var invoiceID int64
	if err := tx.QueryRow(ctx, "SELECT coalesce(max(invoice_id), 0) + 1 FROM invoice").Scan(&invoiceID); err != nil {
		return nil, err
	}
	_, err = tx.Exec(ctx, `
        INSERT INTO invoice (invoice_id, account_key, created_at, amount, flight_details)
        VALUES ($1, $2, now(), $3, $4)`, invoiceID, accountKey, amount, flightDetails)
	if err != nil {
		return nil, err
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, err
	}
	return map[string]any{
		"invoice_id": invoiceID, "amount": amount,
		"flight_details": flightDetails, "status": "invoiced",
	}, nil
}

func (d *DB) RecordBooking(ctx context.Context, accountKey string, items []ItineraryItem, summary string) (map[string]any, error) {
	if len(items) == 0 {
		return nil, &BusinessError{Message: "Nothing to book — the itinerary is empty."}
	}
	total := 0.0
	for _, item := range items {
		total += item.Price
	}
	total = round2(total)

	tx, err := d.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var bookingID, lineID int64
	if err := tx.QueryRow(ctx, "SELECT coalesce(max(booking_id), 0) + 1 FROM booking").Scan(&bookingID); err != nil {
		return nil, err
	}
	if _, err := tx.Exec(ctx, `
        INSERT INTO booking (booking_id, account_key, created_at, total, summary)
        VALUES ($1, $2, now(), $3, $4)`, bookingID, accountKey, total, summary); err != nil {
		return nil, err
	}
	if err := tx.QueryRow(ctx, "SELECT coalesce(max(booking_line_id), 0) FROM booking_line").Scan(&lineID); err != nil {
		return nil, err
	}
	for _, item := range items {
		lineID++
		if _, err := tx.Exec(ctx, `
            INSERT INTO booking_line (booking_line_id, booking_id, kind, ref_id, title, price)
            VALUES ($1, $2, $3, $4, $5, $6)`,
			lineID, bookingID, item.Kind, item.RefID, item.Title, item.Price); err != nil {
			return nil, err
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, err
	}
	return map[string]any{"booking_id": bookingID, "items": items, "total": total}, nil
}

func defaultFlightDate(now time.Time) string { return now.AddDate(0, 0, 21).Format("2006-01-02") }

func monthNumber(value any) int {
	if value == nil {
		return 0
	}
	text := strings.ToLower(strings.TrimSpace(fmt.Sprint(value)))
	if text == "" {
		return 0
	}
	months := []string{"january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"}
	for i, month := range months {
		if text == month || text == month[:3] {
			return i + 1
		}
	}
	parts := strings.Split(text, "-")
	if len(parts) >= 2 {
		text = parts[1]
	}
	number, err := strconv.Atoi(text)
	if err != nil || number < 1 || number > 12 {
		return 0
	}
	return number
}

func rebaseEventDates(startISO, endISO string, now time.Time) (string, string) {
	start, startErr := time.Parse("2006-01-02", startISO)
	end, endErr := time.Parse("2006-01-02", endISO)
	if startErr != nil || endErr != nil {
		return startISO, endISO
	}
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	startThisYear := time.Date(now.Year(), start.Month(), start.Day(), 0, 0, 0, 0, time.UTC)
	targetYear := now.Year()
	if startThisYear.Before(today) {
		targetYear++
	}
	delta := targetYear - start.Year()
	return start.AddDate(delta, 0, 0).Format("2006-01-02"), end.AddDate(delta, 0, 0).Format("2006-01-02")
}

func stringValue(value any) string {
	if value == nil {
		return ""
	}
	if text, ok := value.(string); ok {
		return text
	}
	return fmt.Sprint(value)
}

func floatValue(value any) float64 {
	switch number := value.(type) {
	case float64:
		return number
	case float32:
		return float64(number)
	case int:
		return float64(number)
	case int32:
		return float64(number)
	case int64:
		return float64(number)
	case jsonNumber:
		result, _ := strconv.ParseFloat(string(number), 64)
		return result
	default:
		result, _ := strconv.ParseFloat(fmt.Sprint(number), 64)
		return result
	}
}

func round2(value float64) float64 {
	return float64(int64(value*100+0.5)) / 100
}

type jsonNumber string

func int64Value(value any) int64 {
	switch number := value.(type) {
	case int64:
		return number
	case int32:
		return int64(number)
	case int:
		return int64(number)
	case float64:
		return int64(number)
	default:
		result, _ := strconv.ParseInt(fmt.Sprint(number), 10, 64)
		return result
	}
}

func businessError(err error) (*BusinessError, bool) {
	var target *BusinessError
	return target, errors.As(err, &target)
}

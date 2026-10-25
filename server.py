"""BeaconWorks ticket dashboard -- Flask app. Run: python3 server.py"""
from flask import Flask, jsonify, request, send_from_directory
import os

from src.lib.customers import get_customer, list_customers
from src.lib.tickets import (
    get_ticket, tickets_for_customer, summarize_tickets, parse_ticket_query,
    filter_tickets, query_tickets, enrich_ticket, enrich_tickets,
)

app = Flask(__name__, static_folder="public", static_url_path="")


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/tickets")
def api_tickets():
    try:
        tickets, total = query_tickets(parse_ticket_query(request.args))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    response = jsonify(enrich_tickets(tickets))
    response.headers["X-Total-Count"] = str(total)
    return response


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})


@app.route("/api/tickets/summary")
def api_tickets_summary():
    try:
        tickets = filter_tickets(parse_ticket_query(request.args))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(summarize_tickets(tickets))


@app.route("/api/tickets/<ticket_id>")
def api_ticket(ticket_id):
    ticket = get_ticket(ticket_id)
    if ticket is None:
        return jsonify({"error": "ticket not found"}), 404
    return jsonify(enrich_ticket(ticket))


@app.route("/api/customers/<customer_id>")
def api_customer(customer_id):
    customer = get_customer(customer_id)
    if customer is None:
        return jsonify({"error": "customer not found", "customer_id": customer_id}), 404
    return jsonify({"name": customer["name"], "segment": customer["segment"]})


@app.route("/api/customers/<customer_id>/tickets")
def api_customer_tickets(customer_id):
    return jsonify(enrich_tickets(tickets_for_customer(customer_id)))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 4000))
    app.run(port=port)

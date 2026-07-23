@tool
extends Control

## Vellum Importer Dock for Godot 4.x
## Queries Vellum HTTP API for published game-ready assets and downloads GLB/textures/audio into res://assets/vellum/

@export var vellum_api_url: String = "http://192.168.68.93:8770"
@export var default_lane: String = "field-ops"

var _http_request: HTTPRequest

func _enter_tree() -> void:
	_http_request = HTTPRequest.new()
	add_child(_http_request)
	_http_request.request_completed.connect(_on_request_completed)

func fetch_lane_assets(lane: String) -> void:
	var url = "%s/api/game-ready/elements?lane=%s" % [vellum_api_url, lane]
	_http_request.request(url)

func _on_request_completed(result: int, response_code: int, headers: PackedStringArray, body: PackedByteArray) -> void:
	if response_code == 200:
		var json = JSON.new()
		var parse_result = json.parse(body.get_string_from_utf8())
		if parse_result == OK:
			var data = json.get_data()
			print("[Vellum] Found %d published asset(s) for Godot." % data.get("count", 0))

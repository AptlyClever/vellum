@tool
extends EditorPlugin

## Vellum Asset Vault Importer — EditorPlugin entry point
## Registered in plugin.cfg; adds the Vellum importer dock to the editor.

const DOCK_SCENE = preload("res://addons/vellum_importer/vellum_importer_dock.gd")

var _dock: Control

func _enter_tree() -> void:
	_dock = DOCK_SCENE.new()
	_dock.name = "Vellum"
	add_control_to_dock(DOCK_SLOT_RIGHT_UL, _dock)

func _exit_tree() -> void:
	if _dock:
		remove_control_from_docks(_dock)
		_dock.queue_free()

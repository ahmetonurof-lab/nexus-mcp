# Copilot Instructions

## jCodemunch-MCP Usage

jCodemunch-MCP is available. Use it instead of native file tools for all code exploration.

### Session Start
1. `resolve_repo`
2. (if missing) `index_folder`
3. `suggest_queries`

### Finding Code
| Goal | Tool |
|---|---|
| Symbol by name | `search_symbols` (use `kind=`, `language=`, `file_pattern=` to narrow) |
| String/comment/TODO | `search_text` (`is_regex=true` for patterns, `context_lines` for context) |
| Database columns | `search_columns` |

### Reading Code
| Step | Tool |
|---|---|
| Before opening a file | `get_file_outline` first |
| One or more symbols | `get_symbol_source` (`symbol_id` for one, `symbol_ids[]` for batch) |
| Symbol + imports | `get_context_bundle` |
| Line range only | `get_file_content` (last resort) |

### Repo Structure
| Goal | Tool |
|---|---|
| Overview | `get_repo_outline` |
| Files | `get_file_tree` |

### Relationships & Impact Analysis
| Goal | Tool |
|---|---|
| What imports a file | `find_importers` |
| Where is a name used | `find_references` |
| Is this identifier used | `check_references` |
| File dependency graph | `get_dependency_graph` |
| What breaks if I change X | `get_blast_radius` (`include_depth_scores=true` for layered risk) |
| What symbols changed in git | `get_changed_symbols` |
| Find unreachable/dead code | `find_dead_code` |
| Most important symbols | `get_symbol_importance` |
| Class hierarchy | `get_class_hierarchy` |
| Callers/callees of a symbol | `get_call_hierarchy` |
| High-risk symbols | `get_hotspots` (complexity × churn) |
| Circular dependencies | `get_dependency_cycles` |
| Symbols by decorator | `search_symbols(decorator="route")` or `get_blast_radius(decorator_filter="...")` |

### Session Awareness
| Goal | Tool |
|---|---|
| Starting a new task | `plan_turn` (confidence + recommended symbols) |
| What have I already read | `get_session_context` |
| After editing a file | `register_edit` (invalidates caches) |

### Retrieval with Token Budget
| Goal | Tool |
|---|---|
| Best-fit context for a task | `get_ranked_context` (query + `token_budget`) |
| Bounded symbol bundle | `get_context_bundle` (`token_budget=` to cap size) |

### After Editing
Call `index_file { "path": "/abs/path" }` to keep the index fresh.

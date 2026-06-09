# Decision Taxonomy

15 categories that cover every architectural concern. The Interrogator uses these as a checklist.

## Critical Categories

These must be resolved before a contract can be built. If any of these are missing, `can_implement: false`.

| ID | Name | Key question type |
|----|------|-------------------|
| `data_model` | Data Model | What fields? What types? What constraints? |
| `api_contract` | API / Interface Contract | What inputs? What outputs? What shape? |
| `implementation_scope` | Implementation Scope | What is explicitly IN scope? What is OUT? |

## Standard Categories

These should be asked when relevant to the task type.

### 1. product_behavior
What should the system do from the user's perspective?
- Example: "Should the user see a success message after save?"
- Example: "Should delete require confirmation?"
- Example: "Should errors be shown inline or as a toast?"

### 2. data_model
What data entities are involved? What fields, types, constraints?
- Example: "What fields does Product have? (name, price, quantity, description?)"
- Example: "Is price required? Can it be null? What is the minimum value?"
- Example: "What is the primary key type? (Long, UUID, String?)"

### 3. api_contract
What is the exact shape of inputs and outputs?
- Example: "Should the API return the entity directly or a DTO?"
- Example: "What fields are in the create request body?"
- Example: "What HTTP status codes should each endpoint return?"

### 4. business_rules
What domain constraints must be enforced?
- Example: "Can price be negative?"
- Example: "What is the maximum order quantity?"
- Example: "Can a user have multiple active sessions?"

### 5. architecture_pattern
Which structural pattern should be used?
- Example: "Repository pattern or direct DB access in service?"
- Example: "Should this use CQRS or a simple service?"
- Example: "Should the mapper be a separate class or inline?"

### 6. state_lifecycle
What states can an entity be in? How does it transition?
- Example: "What statuses can an Order have? (PENDING, CONFIRMED, SHIPPED, CANCELLED)"
- Example: "Can a cancelled order be reactivated?"
- Example: "Should status changes be logged?"

### 7. validation
Where and how should input validation happen?
- Example: "Should validation happen at controller layer or service layer?"
- Example: "Should we use Bean Validation annotations or manual checks?"
- Example: "What error message format should validation failures use?"

### 8. error_handling
How should errors be caught and surfaced?
- Example: "What HTTP status code for not-found? (404 with body or 204?)"
- Example: "Should we use a global exception handler?"
- Example: "Should error responses include a stack trace in dev mode?"

### 9. security_permission
Who can access what?
- Example: "Should this endpoint require JWT authentication?"
- Example: "Which roles can delete? (admin only, or any authenticated user?)"
- Example: "Should the API expose user IDs or use opaque tokens?"

### 10. persistence_transaction
How is data stored? What consistency guarantees?
- Example: "Should this create + publish event be wrapped in a transaction?"
- Example: "Should we use optimistic locking for concurrent updates?"
- Example: "Should soft-deleted records be excluded from all queries?"

### 11. performance_concurrency
What performance constraints? Concurrent access handling?
- Example: "Should this endpoint be cached? For how long?"
- Example: "Will this be called by many concurrent users? Need connection pooling?"
- Example: "Should batch operations be chunked?"

### 12. observability
What needs to be logged or monitored?
- Example: "Should we log when a product is created?"
- Example: "Should failed login attempts emit a metric?"
- Example: "Should we add a correlation ID to request logs?"

### 13. testing
What test coverage is required?
- Example: "Should this have unit tests? Integration tests? Both?"
- Example: "Should we test the happy path only or also edge cases?"
- Example: "Should tests be in scope for this implementation step?"

### 14. migration_compatibility
How do we handle existing data and backward compatibility?
- Example: "Does this field addition require a database migration?"
- Example: "Will this API change break existing clients?"
- Example: "Should old data be backfilled?"

### 15. implementation_scope
What is explicitly in and out of scope?
- Example: "Implement only the entity now, or also service and controller?"
- Example: "Include tests in this step or add them later?"
- Example: "Should we implement only login, or also register and logout?"

## How the Interrogator Uses These

For any requirement, the Interrogator:
1. Checks which categories are relevant
2. Checks which decisions already exist in project memory
3. Asks only about relevant + unresolved categories
4. Marks critical categories (data_model, api_contract, implementation_scope) as required
5. Marks optional categories based on task type

A task with `can_implement: false` means at least one critical category is unresolved.

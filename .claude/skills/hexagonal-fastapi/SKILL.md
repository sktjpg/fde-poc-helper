---
name: hexagonal-fastapi
description: How to add endpoints, use cases, ports and adapters in this FastAPI codebase while keeping the hexagonal dependency rule. Use when adding or changing an endpoint, a service, an external integration (HTTP API, database, LLM provider), or when deciding which layer a piece of code belongs to.
---

# Hexagonal FastAPI

The core does not know about HTTP, SDKs or databases. It talks to the world through ports
(Protocols in `app/domain/ports.py`); adapters implement them; `app/dependencies.py` wires
them together. The pay-off is concrete: every use case is testable with a fake, and swapping
a provider touches one adapter and one line of wiring.

## Decide the layer first

| The code...                                        | Lives in                     |
|----------------------------------------------------|------------------------------|
| is a data shape or a business rule, no I/O          | `domain/`                    |
| orchestrates steps to fulfil one request            | `services/`                  |
| decides which tool to call next (LLM-driven)        | `agents/`                    |
| talks to something outside the process              | `adapters/` behind a port    |
| translates HTTP to a service call                   | `api/`                       |
| constructs objects and chooses implementations      | `dependencies.py`            |

If a small requirement fits in one existing file, put it there. Do not create a port for
something with one implementation and no I/O.

## Recipe: new endpoint backed by a use case

1. Schemas in `app/api/schemas.py` (request) and, if the response is a domain concept, a
   frozen model in `app/domain/models.py`.
2. Service in `app/services/<name>.py`: a frozen dataclass holding its ports, one public
   async method. No FastAPI imports.
3. Provider in `app/dependencies.py` that builds the service from `Depends(...)` providers.
4. Route in `app/api/routes.py`: parse, call the service, return. Declare `response_model`
   and the error responses.
5. Tests: service test with fakes, API test with `app.dependency_overrides`.

```python
# app/api/routes.py
@router.post(
    "/orders/{order_id}/status",
    response_model=OrderStatus,
    responses={404: {"model": ErrorResponse}},
)
async def order_status(
    order_id: str,
    service: Annotated[OrderService, Depends(get_order_service)],
) -> OrderStatus:
    return await service.status(order_id)
```

## Recipe: new external dependency

1. Port: a `Protocol` in `app/domain/ports.py`, named for what the core needs
   (`InvoiceGateway.invoice_for(invoice_id)`), not for the technology.
2. Adapter in `app/adapters/<kind>/<tech>.py`. It owns the SDK or `httpx` client, sets a
   timeout, validates the response into a domain model, and converts every SDK/HTTP
   exception into a domain error (chain with `from exc`).
3. A fake implementing the same port for tests (in the test file, or next to the adapter if
   it is reused, like `ScriptedLLM`).
4. Bind it in `app/dependencies.py`.
5. Extend `FORBIDDEN` in `tests/test_architecture.py` if a new SDK must stay out of the core.

```python
# app/adapters/billing/http_invoices.py
class HttpInvoices:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def invoice_for(self, invoice_id: str) -> Invoice:
        try:
            response = await self._client.get(f"/invoices/{invoice_id}")
            response.raise_for_status()
            return Invoice.model_validate(response.json())
        except httpx.TimeoutException as exc:
            raise ExternalServiceError("Billing service timed out", retryable=True) from exc
        except (httpx.HTTPStatusError, ValidationError) as exc:
            raise ExternalServiceError("Billing service returned an unusable response") from exc
```

## FastAPI specifics

- Errors: raise domain errors in the core; map them to status codes once, in the exception
  handlers of `app/main.py`. Routes do not contain `try/except`.
- Status codes: 422 invalid input, 404 missing resource, 409 conflict, 502 upstream failed,
  503 upstream temporarily unavailable, 504 upstream timed out.
- Shared clients (`httpx.AsyncClient`, DB pools) are created in the `lifespan` in
  `app/main.py` and closed there, not per request.
- `Annotated[T, Depends(provider)]` for injection; override providers in tests.
- Never block the event loop: no `requests`, no `time.sleep`; wrap unavoidable blocking calls
  with `asyncio.to_thread`.
- Bound fan-out with `asyncio.Semaphore` when calling external services in parallel.

## What to say aloud

"The use case depends on a port, not on the vendor SDK, so I can test it with a fake and
swap the provider without touching business logic. The route only translates HTTP."

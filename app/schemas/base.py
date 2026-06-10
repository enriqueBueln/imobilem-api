"""Shared Pydantic base for API schemas.

The Expo app speaks camelCase; Python speaks snake_case. `CamelModel` bridges both:
fields are declared snake_case here but (de)serialized as camelCase over the wire,
so `sap_user_id` becomes `sapUserId` in JSON. Apply it to every request/response
schema so the API contract stays consistent across all domains.

- alias_generator=to_camel -> JSON keys are camelCase
- populate_by_name=True     -> still constructible by field name (TokenResponse(access_token=...))
- from_attributes=True      -> build straight from SQLAlchemy ORM objects
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )

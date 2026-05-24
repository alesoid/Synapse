from fastapi import HTTPException, status

ROLES: dict[str, int] = {
    "junior": 1,
    "middle": 2,
    "senior": 3,
    "manager": 4,
    "admin": 5,
}


def role_to_access_level(role: str | None) -> int:
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="X-User-Role header is required.",
        )
    normalized = role.lower()
    if normalized not in ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Unknown role: {role}",
        )
    return ROLES[normalized]


def require_min_access(role: str | None, required_level: int, message: str) -> int:
    access_level = role_to_access_level(role)
    if access_level < required_level:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=message,
        )
    return access_level


def require_admin(role: str | None) -> int:
    return require_min_access(role, ROLES["admin"], "Admin role is required.")


def require_manager_or_admin(role: str | None) -> int:
    return require_min_access(
        role,
        ROLES["manager"],
        "Manager or admin role is required.",
    )


def filter_authorized_items(items: list[dict], user_access_level: int) -> list[dict]:
    """Return items whose access_level ≤ user_access_level.

    NULL access_level is treated as 1 (public), consistent with the
    COALESCE(n.access_level, 1) pattern used in Cypher queries.
    An item with no access_level label is public — not a bypass.
    """
    return [
        item
        for item in items
        # COALESCE(access_level, 1): None → level 1 (public), same as Cypher
        if (item.get("access_level") if item.get("access_level") is not None else 1)
        <= user_access_level
    ]

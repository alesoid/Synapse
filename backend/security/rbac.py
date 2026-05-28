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



from enum import Enum


class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    COLLEGE_ADMIN = "college_admin"
    FACULTY = "faculty"
    STUDENT = "student"
    PARENT = "parent"
    WARDEN = "warden"


class CollegePlan(str, Enum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class CollegeStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING = "pending"

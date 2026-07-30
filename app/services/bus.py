import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from beanie import PydanticObjectId
from app.models.bus import Bus, BusLocation, BusRoute, BusStop, StudentBusAssignment
from app.models.student import Student
from app.models.user import User

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BusService:
    @staticmethod
    async def create_bus(
        college_id: PydanticObjectId,
        bus_number: str,
        driver_name: str,
        driver_phone: str,
        capacity: int = 40,
        route_id: Optional[PydanticObjectId] = None,
        status: str = "active"
    ) -> Bus:
        route_name = None
        if route_id:
            route = await BusRoute.get(route_id)
            if route:
                route_name = route.route_name

        bus = Bus(
            college_id=college_id,
            bus_number=bus_number,
            driver_name=driver_name,
            driver_phone=driver_phone,
            route_id=route_id,
            route_name=route_name,
            capacity=capacity,
            status=status,
        )
        await bus.insert()

        # Seed initial default location if none exists
        init_lat = 12.9716  # Default campus lat
        init_lng = 77.5946  # Default campus lng
        if route_id:
            route = await BusRoute.get(route_id)
            if route and route.stops and len(route.stops) > 0:
                init_lat = route.stops[0].latitude
                init_lng = route.stops[0].longitude

        await BusService.update_bus_location(
            bus_id=bus.id,
            college_id=college_id,
            latitude=init_lat,
            longitude=init_lng,
            speed=0.0,
            status="idle"
        )

        return bus

    @staticmethod
    async def update_bus(
        bus_id: PydanticObjectId,
        college_id: PydanticObjectId,
        bus_number: Optional[str] = None,
        driver_name: Optional[str] = None,
        driver_phone: Optional[str] = None,
        capacity: Optional[int] = None,
        route_id: Optional[PydanticObjectId] = None,
        status: Optional[str] = None
    ) -> Optional[Bus]:
        bus = await Bus.find_one(Bus.id == bus_id, Bus.college_id == college_id)
        if not bus:
            return None

        if bus_number is not None:
            bus.bus_number = bus_number
        if driver_name is not None:
            bus.driver_name = driver_name
        if driver_phone is not None:
            bus.driver_phone = driver_phone
        if capacity is not None:
            bus.capacity = capacity
        if status is not None:
            bus.status = status
        if route_id is not None:
            bus.route_id = route_id
            route = await BusRoute.get(route_id)
            bus.route_name = route.route_name if route else None

        bus.updated_at = utcnow()
        await bus.save()
        return bus

    @staticmethod
    async def delete_bus(bus_id: PydanticObjectId, college_id: PydanticObjectId) -> bool:
        bus = await Bus.find_one(Bus.id == bus_id, Bus.college_id == college_id)
        if not bus:
            return False
        await bus.delete()
        await StudentBusAssignment.find(StudentBusAssignment.bus_id == bus_id).delete()
        await BusLocation.find(BusLocation.bus_id == bus_id).delete()
        return True

    @staticmethod
    async def get_buses(college_id: PydanticObjectId) -> List[Bus]:
        return await Bus.find(Bus.college_id == college_id).to_list()

    @staticmethod
    async def get_bus_by_id(bus_id: PydanticObjectId, college_id: PydanticObjectId) -> Optional[Bus]:
        return await Bus.find_one(Bus.id == bus_id, Bus.college_id == college_id)

    # ROUTE METHODS
    @staticmethod
    async def create_route(
        college_id: PydanticObjectId,
        route_name: str,
        stops: List[Dict[str, Any]],
        timings: Optional[str] = None
    ) -> BusRoute:
        parsed_stops = [
            BusStop(
                name=s.get("name", "Stop"),
                latitude=float(s.get("latitude", 12.9716)),
                longitude=float(s.get("longitude", 77.5946)),
                estimated_time=s.get("estimated_time")
            )
            for s in stops
        ]
        route = BusRoute(
            college_id=college_id,
            route_name=route_name,
            stops=parsed_stops,
            timings=timings
        )
        await route.insert()
        return route

    @staticmethod
    async def update_route(
        route_id: PydanticObjectId,
        college_id: PydanticObjectId,
        route_name: Optional[str] = None,
        stops: Optional[List[Dict[str, Any]]] = None,
        timings: Optional[str] = None
    ) -> Optional[BusRoute]:
        route = await BusRoute.find_one(BusRoute.id == route_id, BusRoute.college_id == college_id)
        if not route:
            return None

        if route_name is not None:
            route.route_name = route_name
        if timings is not None:
            route.timings = timings
        if stops is not None:
            route.stops = [
                BusStop(
                    name=s.get("name", "Stop"),
                    latitude=float(s.get("latitude", 12.9716)),
                    longitude=float(s.get("longitude", 77.5946)),
                    estimated_time=s.get("estimated_time")
                )
                for s in stops
            ]

        route.updated_at = utcnow()
        await route.save()
        return route

    @staticmethod
    async def delete_route(route_id: PydanticObjectId, college_id: PydanticObjectId) -> bool:
        route = await BusRoute.find_one(BusRoute.id == route_id, BusRoute.college_id == college_id)
        if not route:
            return False
        await route.delete()
        # Clear route association from buses
        buses = await Bus.find(Bus.route_id == route_id).to_list()
        for b in buses:
            b.route_id = None
            b.route_name = None
            await b.save()
        return True

    @staticmethod
    async def get_routes(college_id: PydanticObjectId) -> List[BusRoute]:
        return await BusRoute.find(BusRoute.college_id == college_id).to_list()

    # ASSIGNMENT METHODS
    @staticmethod
    async def assign_student(
        college_id: PydanticObjectId,
        student_id: PydanticObjectId,
        bus_id: PydanticObjectId,
        route_id: PydanticObjectId,
        stop_name: Optional[str] = None
    ) -> StudentBusAssignment:
        # Check existing
        existing = await StudentBusAssignment.find_one(
            StudentBusAssignment.college_id == college_id,
            StudentBusAssignment.student_id == student_id
        )
        if existing:
            existing.bus_id = bus_id
            existing.route_id = route_id
            existing.stop_name = stop_name
            await existing.save()
            return existing

        assignment = StudentBusAssignment(
            college_id=college_id,
            student_id=student_id,
            bus_id=bus_id,
            route_id=route_id,
            stop_name=stop_name
        )
        await assignment.insert()
        return assignment

    @staticmethod
    async def remove_assignment(assignment_id: PydanticObjectId, college_id: PydanticObjectId) -> bool:
        assignment = await StudentBusAssignment.find_one(
            StudentBusAssignment.id == assignment_id,
            StudentBusAssignment.college_id == college_id
        )
        if not assignment:
            return False
        await assignment.delete()
        return True

    @staticmethod
    async def get_assignments(college_id: PydanticObjectId) -> List[Dict[str, Any]]:
        assignments = await StudentBusAssignment.find(StudentBusAssignment.college_id == college_id).to_list()
        result = []
        for a in assignments:
            user = await User.get(a.student_id)
            student = await Student.find_one(Student.user_id == a.student_id)
            if not student:
                student = await Student.get(a.student_id)
            bus = await Bus.get(a.bus_id)
            route = await BusRoute.get(a.route_id)

            result.append({
                "id": str(a.id),
                "student_id": str(a.student_id),
                "student_name": user.name if user else "Student",
                "roll_no": student.roll_no if student else "N/A",
                "bus_id": str(a.bus_id),
                "bus_number": bus.bus_number if bus else "N/A",
                "route_id": str(a.route_id),
                "route_name": route.route_name if route else "N/A",
                "stop_name": a.stop_name,
                "created_at": a.created_at.isoformat()
            })
        return result

    # LOCATION & GPS METHODS
    @staticmethod
    async def update_bus_location(
        bus_id: PydanticObjectId,
        college_id: PydanticObjectId,
        latitude: float,
        longitude: float,
        speed: float = 0.0,
        status: str = "moving"
    ) -> BusLocation:
        loc = BusLocation(
            bus_id=bus_id,
            college_id=college_id,
            latitude=latitude,
            longitude=longitude,
            speed=speed,
            status=status,
            timestamp=utcnow()
        )
        await loc.insert()

        # Also update bus status if provided
        bus = await Bus.get(bus_id)
        if bus:
            bus.status = status if status in ("active", "in_transit", "maintenance", "inactive") else "in_transit"
            bus.updated_at = utcnow()
            await bus.save()

        return loc

    @staticmethod
    async def get_latest_bus_location(bus_id: PydanticObjectId, college_id: Optional[PydanticObjectId] = None) -> Optional[BusLocation]:
        if college_id:
            locs = await BusLocation.find(
                BusLocation.bus_id == bus_id,
                BusLocation.college_id == college_id
            ).sort("-timestamp").limit(1).to_list()
        else:
            locs = await BusLocation.find(
                BusLocation.bus_id == bus_id
            ).sort("-timestamp").limit(1).to_list()

        return locs[0] if locs else None

    @staticmethod
    async def get_student_assigned_bus(student_user_id: PydanticObjectId, college_id: Optional[PydanticObjectId] = None) -> Optional[Dict[str, Any]]:
        # Find student record or user
        student = await Student.find_one(Student.user_id == student_user_id)
        search_ids = [student_user_id]
        if student:
            search_ids.append(student.id)

        assignment = None
        for sid in search_ids:
            if college_id:
                assignment = await StudentBusAssignment.find_one(
                    StudentBusAssignment.student_id == sid,
                    StudentBusAssignment.college_id == college_id
                )
            else:
                assignment = await StudentBusAssignment.find_one(
                    StudentBusAssignment.student_id == sid
                )
            if assignment:
                break

        if not assignment:
            # If no direct assignment, check if there is a default active bus for the college
            buses = await Bus.find(Bus.college_id == (college_id or (student.college_id if student else None))).to_list()
            if not buses:
                return None
            bus = buses[0]
            route = await BusRoute.get(bus.route_id) if bus.route_id else None
        else:
            bus = await Bus.get(assignment.bus_id)
            route = await BusRoute.get(assignment.route_id)

        if not bus:
            return None

        location = await BusService.get_latest_bus_location(bus.id, bus.college_id)

        # Dynamic ETA estimate (minutes)
        eta_minutes = 12 if bus.status == "in_transit" else (5 if bus.status == "active" else 0)

        return {
            "assignment": {
                "id": str(assignment.id) if assignment else None,
                "stop_name": assignment.stop_name if assignment else (route.stops[0].name if route and route.stops else "Campus Main Gate"),
            },
            "bus": {
                "id": str(bus.id),
                "bus_number": bus.bus_number,
                "driver_name": bus.driver_name,
                "driver_phone": bus.driver_phone,
                "capacity": bus.capacity,
                "status": bus.status,
            },
            "route": {
                "id": str(route.id) if route else None,
                "route_name": route.route_name if route else "Main Route",
                "timings": route.timings if route else "07:30 AM - 05:30 PM",
                "stops": [
                    {
                        "name": s.name,
                        "latitude": s.latitude,
                        "longitude": s.longitude,
                        "estimated_time": s.estimated_time or "N/A"
                    }
                    for s in (route.stops if route else [])
                ]
            },
            "location": {
                "latitude": location.latitude if location else 12.9716,
                "longitude": location.longitude if location else 77.5946,
                "speed": location.speed if location else 35.5,
                "status": location.status if location else "moving",
                "timestamp": location.timestamp.isoformat() if location else utcnow().isoformat()
            },
            "eta_minutes": eta_minutes
        }

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from beanie import PydanticObjectId
from app.models.hostel import HostelBuilding, HostelRequest, Outpass, Room, RoomAllocation
from app.models.student import Student
from app.models.user import User

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HostelService:
    # --- BUILDING MANAGEMENT ---
    @staticmethod
    async def create_building(
        college_id: PydanticObjectId,
        name: str,
        total_floors: int = 1,
        total_rooms: int = 0,
        gender: Optional[str] = "unisex",
        status: str = "active",
        description: Optional[str] = None
    ) -> HostelBuilding:
        building = HostelBuilding(
            college_id=college_id,
            name=name,
            total_floors=total_floors,
            total_rooms=total_rooms,
            gender=gender,
            status=status,
            description=description
        )
        await building.insert()
        return building

    @staticmethod
    async def get_buildings(college_id: PydanticObjectId) -> List[HostelBuilding]:
        return await HostelBuilding.find(HostelBuilding.college_id == college_id).to_list()

    @staticmethod
    async def update_building(
        building_id: PydanticObjectId,
        college_id: PydanticObjectId,
        name: Optional[str] = None,
        total_floors: Optional[int] = None,
        total_rooms: Optional[int] = None,
        gender: Optional[str] = None,
        status: Optional[str] = None,
        description: Optional[str] = None
    ) -> Optional[HostelBuilding]:
        building = await HostelBuilding.find_one(HostelBuilding.id == building_id, HostelBuilding.college_id == college_id)
        if not building:
            return None
        if name is not None:
            building.name = name
        if total_floors is not None:
            building.total_floors = total_floors
        if total_rooms is not None:
            building.total_rooms = total_rooms
        if gender is not None:
            building.gender = gender
        if status is not None:
            building.status = status
        if description is not None:
            building.description = description
        building.updated_at = utcnow()
        await building.save()
        return building

    @staticmethod
    async def delete_building(building_id: PydanticObjectId, college_id: PydanticObjectId) -> bool:
        building = await HostelBuilding.find_one(HostelBuilding.id == building_id, HostelBuilding.college_id == college_id)
        if not building:
            return False
        await building.delete()
        # Clear building_id from associated rooms
        rooms = await Room.find(Room.building_id == building_id).to_list()
        for r in rooms:
            r.building_id = None
            await r.save()
        return True

    # --- ROOM MANAGEMENT ---
    @staticmethod
    async def create_room(
        college_id: PydanticObjectId,
        room_number: str,
        hostel_name: str,
        building_id: Optional[PydanticObjectId] = None,
        block: Optional[str] = None,
        floor: int = 1,
        capacity: int = 2,
        room_type: str = "double",
        status: str = "available",
        amenities: Optional[List[str]] = None
    ) -> Room:
        if building_id:
            bld = await HostelBuilding.get(building_id)
            if bld:
                hostel_name = bld.name

        room = Room(
            college_id=college_id,
            building_id=building_id,
            hostel_name=hostel_name,
            block=block,
            floor=floor,
            room_number=room_number,
            capacity=capacity,
            occupied=0,
            room_type=room_type,
            status=status,
            amenities=amenities or ["Bed", "Study Table", "Wardrobe"],
            is_available=True
        )
        await room.insert()

        # Update total_rooms count in building if linked
        if building_id:
            bld = await HostelBuilding.get(building_id)
            if bld:
                bld.total_rooms = await Room.find(Room.building_id == building_id).count()
                await bld.save()

        return room

    @staticmethod
    async def update_room(
        room_id: PydanticObjectId,
        college_id: PydanticObjectId,
        room_number: Optional[str] = None,
        hostel_name: Optional[str] = None,
        building_id: Optional[PydanticObjectId] = None,
        block: Optional[str] = None,
        floor: Optional[int] = None,
        capacity: Optional[int] = None,
        room_type: Optional[str] = None,
        status: Optional[str] = None,
        amenities: Optional[List[str]] = None
    ) -> Optional[Room]:
        room = await Room.find_one(Room.id == room_id, Room.college_id == college_id)
        if not room:
            return None

        if room_number is not None:
            room.room_number = room_number
        if hostel_name is not None:
            room.hostel_name = hostel_name
        if building_id is not None:
            room.building_id = building_id
            bld = await HostelBuilding.get(building_id)
            if bld:
                room.hostel_name = bld.name
        if block is not None:
            room.block = block
        if floor is not None:
            room.floor = floor
        if capacity is not None:
            room.capacity = capacity
            # recheck availability
            room.is_available = room.occupied < capacity
            if room.occupied >= capacity:
                room.status = "occupied"
        if room_type is not None:
            room.room_type = room_type
        if status is not None:
            room.status = status
        if amenities is not None:
            room.amenities = amenities

        room.updated_at = utcnow()
        await room.save()
        return room

    @staticmethod
    async def delete_room(room_id: PydanticObjectId, college_id: PydanticObjectId) -> bool:
        room = await Room.find_one(Room.id == room_id, Room.college_id == college_id)
        if not room or room.occupied > 0:
            return False
        building_id = room.building_id
        await room.delete()

        if building_id:
            bld = await HostelBuilding.get(building_id)
            if bld:
                bld.total_rooms = await Room.find(Room.building_id == building_id).count()
                await bld.save()
        return True

    # --- ROOM ALLOCATION LOGIC ---
    @staticmethod
    async def allocate_room(
        college_id: PydanticObjectId,
        student_id: str,  # user_id
        room_id: PydanticObjectId,
        allocated_by: str,
        remarks: Optional[str] = None
    ) -> RoomAllocation:
        # Rule 1: Check if room exists and has available capacity
        room = await Room.find_one(Room.id == room_id, Room.college_id == college_id)
        if not room:
            raise ValueError("Room not found")
        if room.occupied >= room.capacity:
            raise ValueError("Room capacity exceeded. No available beds.")

        # Rule 2: Check if student already has an active allocation
        existing_alloc = await RoomAllocation.find_one(
            RoomAllocation.college_id == college_id,
            RoomAllocation.student_id == student_id,
            RoomAllocation.status == "active"
        )
        if existing_alloc:
            raise ValueError("Student already has an active room allocation. Change or vacate existing room first.")

        # Perform allocation
        alloc = RoomAllocation(
            college_id=college_id,
            student_id=student_id,
            room_id=room_id,
            allocated_by=allocated_by,
            allocated_date=utcnow(),
            status="active",
            remarks=remarks
        )
        await alloc.insert()

        # Update room occupants
        if student_id not in room.student_ids:
            room.student_ids.append(student_id)
        room.current_student_ids = room.student_ids
        room.occupied = len(room.student_ids)
        if room.occupied >= room.capacity:
            room.status = "occupied"
            room.is_available = False
        else:
            room.status = "available"
            room.is_available = True
        room.updated_at = utcnow()
        await room.save()

        # Also sync user profile hostel name
        user = await User.get(PydanticObjectId(student_id) if len(student_id) == 24 else student_id)
        if user:
            user.profile["hostel"] = f"{room.hostel_name} - Room {room.room_number}"
            await user.save()

        return alloc

    @staticmethod
    async def change_room(
        college_id: PydanticObjectId,
        student_id: str,
        new_room_id: PydanticObjectId,
        allocated_by: str,
        remarks: Optional[str] = None
    ) -> RoomAllocation:
        # Vacate old room first if active
        existing_alloc = await RoomAllocation.find_one(
            RoomAllocation.college_id == college_id,
            RoomAllocation.student_id == student_id,
            RoomAllocation.status == "active"
        )
        if existing_alloc:
            await HostelService.vacate_room(
                allocation_id=existing_alloc.id,
                college_id=college_id,
                remarks=f"Changed room to new room {new_room_id}"
            )
            existing_alloc.status = "changed"
            await existing_alloc.save()

        # Allocate new room
        return await HostelService.allocate_room(
            college_id=college_id,
            student_id=student_id,
            room_id=new_room_id,
            allocated_by=allocated_by,
            remarks=remarks or "Room changed"
        )

    @staticmethod
    async def vacate_room(
        allocation_id: PydanticObjectId,
        college_id: PydanticObjectId,
        remarks: Optional[str] = None
    ) -> bool:
        alloc = await RoomAllocation.find_one(RoomAllocation.id == allocation_id, RoomAllocation.college_id == college_id)
        if not alloc or alloc.status != "active":
            return False

        alloc.status = "vacated"
        alloc.vacated_date = utcnow()
        if remarks:
            alloc.remarks = remarks
        await alloc.save()

        # Update room occupied count
        room = await Room.get(alloc.room_id)
        if room:
            if alloc.student_id in room.student_ids:
                room.student_ids.remove(alloc.student_id)
            room.current_student_ids = room.student_ids
            room.occupied = len(room.student_ids)
            room.is_available = room.occupied < room.capacity
            if room.occupied == 0:
                room.status = "available"
            elif room.occupied < room.capacity:
                room.status = "available"
            room.updated_at = utcnow()
            await room.save()

        # Clear student profile hostel
        user = await User.get(PydanticObjectId(alloc.student_id) if len(alloc.student_id) == 24 else alloc.student_id)
        if user and "hostel" in user.profile:
            user.profile.pop("hostel", None)
            await user.save()

        return True

    # --- HOSTEL REQUESTS ---
    @staticmethod
    async def create_request(
        college_id: PydanticObjectId,
        student_id: str,
        preferred_hostel: str,
        request_reason: str
    ) -> HostelRequest:
        req = HostelRequest(
            college_id=college_id,
            student_id=student_id,
            preferred_hostel=preferred_hostel,
            request_reason=request_reason,
            status="pending"
        )
        await req.insert()
        return req

    @staticmethod
    async def approve_request(
        request_id: PydanticObjectId,
        college_id: PydanticObjectId,
        approved_by: str,
        allocated_room_id: Optional[PydanticObjectId] = None,
        remarks: Optional[str] = None
    ) -> HostelRequest:
        req = await HostelRequest.find_one(HostelRequest.id == request_id, HostelRequest.college_id == college_id)
        if not req:
            raise ValueError("Request not found")

        req.status = "approved" if not allocated_room_id else "allocated"
        req.approved_by = approved_by
        req.remarks = remarks
        req.updated_at = utcnow()

        if allocated_room_id:
            req.allocated_room_id = allocated_room_id
            await HostelService.allocate_room(
                college_id=college_id,
                student_id=req.student_id,
                room_id=allocated_room_id,
                allocated_by=approved_by,
                remarks=f"Allocated via request #{req.id}"
            )

        await req.save()
        return req

    @staticmethod
    async def reject_request(
        request_id: PydanticObjectId,
        college_id: PydanticObjectId,
        approved_by: str,
        remarks: Optional[str] = None
    ) -> HostelRequest:
        req = await HostelRequest.find_one(HostelRequest.id == request_id, HostelRequest.college_id == college_id)
        if not req:
            raise ValueError("Request not found")

        req.status = "rejected"
        req.approved_by = approved_by
        req.remarks = remarks
        req.updated_at = utcnow()
        await req.save()
        return req

    # --- STATS & DASHBOARD ---
    @staticmethod
    async def get_hostel_stats(college_id: PydanticObjectId) -> Dict[str, Any]:
        buildings_count = await HostelBuilding.find(HostelBuilding.college_id == college_id).count()
        rooms = await Room.find(Room.college_id == college_id).to_list()
        
        total_rooms = len(rooms)
        occupied_rooms = sum(1 for r in rooms if r.occupied > 0)
        available_rooms = sum(1 for r in rooms if r.occupied < r.capacity and r.status != "maintenance")
        total_capacity = sum(r.capacity for r in rooms)
        total_occupied = sum(r.occupied for r in rooms)
        
        pending_requests = await HostelRequest.find(
            HostelRequest.college_id == college_id,
            HostelRequest.status == "pending"
        ).count()

        active_allocations = await RoomAllocation.find(
            RoomAllocation.college_id == college_id,
            RoomAllocation.status == "active"
        ).count()

        pending_outpasses = await Outpass.find(
            Outpass.college_id == college_id,
            Outpass.status == "pending"
        ).count()

        return {
            "total_buildings": buildings_count,
            "total_rooms": total_rooms,
            "occupied_rooms": occupied_rooms,
            "available_rooms": available_rooms,
            "total_capacity": total_capacity,
            "total_occupied": total_occupied,
            "hostel_students": active_allocations,
            "pending_requests": pending_requests,
            "pending_outpasses": pending_outpasses,
            "occupancy_percentage": round((total_occupied / total_capacity * 100), 1) if total_capacity > 0 else 0
        }

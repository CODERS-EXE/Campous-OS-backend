import base64
import logging
from typing import Any, Dict, List, Optional
import httpx

from beanie import PydanticObjectId
from app.core.config import get_settings
from app.models.ai import AiChatMessage
from app.models.assignment import Assignment
from app.models.attendance import Attendance
from app.models.college import College
from app.models.faculty import Faculty
from app.models.hostel import Outpass, Room
from app.models.result import Result
from app.models.student import Student
from app.models.timetable import TimetableEntry
from app.models.user import User

logger = logging.getLogger(__name__)
settings = get_settings()

# History kept per user in DB; only last N sent to LLM to avoid token overflow
HISTORY_CONTEXT_LIMIT = 10
HISTORY_FETCH_LIMIT = 50


class AiService:

    # ── Chat History ────────────────────────────────────────────────────────────

    @staticmethod
    async def get_chat_history(user_id: PydanticObjectId, limit: int = HISTORY_FETCH_LIMIT) -> List[AiChatMessage]:
        return await AiChatMessage.find(
            AiChatMessage.user_id == user_id
        ).sort("+created_at").limit(limit).to_list()

    @staticmethod
    async def save_message(
        user_id: PydanticObjectId,
        college_id: Optional[PydanticObjectId],
        role: str,
        sender: str,
        content: str
    ) -> AiChatMessage:
        msg = AiChatMessage(
            user_id=user_id,
            college_id=college_id,
            role=role,
            sender=sender,
            content=content
        )
        await msg.insert()
        return msg

    @staticmethod
    async def clear_chat_history(user_id: PydanticObjectId) -> None:
        await AiChatMessage.find(AiChatMessage.user_id == user_id).delete()

    # ── Role Suggestions ────────────────────────────────────────────────────────

    @staticmethod
    def get_role_suggestions(role: str) -> List[str]:
        if role == "student":
            return [
                "What is my current attendance percentage?",
                "Show my recent exam results and grades",
                "What assignments are due soon?",
                "What is my schedule for today?",
                "How can I prepare for my upcoming exams?",
            ]
        elif role == "faculty":
            return [
                "Show attendance summary for my classes",
                "What is the average performance of my students?",
                "Which assignments need evaluation?",
                "What is my teaching schedule for today?",
                "How can I improve student engagement?",
            ]
        elif role == "parent":
            return [
                "How is my child's attendance record?",
                "What are my child's latest exam results?",
                "Are there any unread college notifications?",
                "What is the fee status for my child?",
                "Is my child's bus tracking active?",
            ]
        elif role in ("college_admin", "super_admin"):
            return [
                "Give me a summary of total students and faculty",
                "What is the overall college attendance rate?",
                "Show department-wise student distribution",
                "Are there any urgent notifications or fee alerts?",
                "Generate an administrative performance report",
            ]
        elif role == "warden":
            return [
                "What is the current hostel room occupancy rate?",
                "How many outpass requests are pending approval?",
                "Show hosteller emergency contact records",
                "List available rooms in block A and B",
                "Show recent hostel activity and outpass logs",
            ]
        return [
            "How can CampusOS AI help me today?",
            "Show system overview and status",
            "What features are available for my role?",
        ]

    # ── Context Gathering ───────────────────────────────────────────────────────

    @classmethod
    async def gather_user_context(cls, user: User, college: Optional[College]) -> Dict[str, Any]:
        """Fetch live MongoDB data based on user role with strict college isolation."""
        col_id = (college.id if college else user.college_id)

        context: Dict[str, Any] = {
            "user_name": user.name,
            "user_email": user.email,
            "role": user.role,
            "college_name": college.name if college else "CampusOS Platform",
        }

        try:
            # ── STUDENT ────────────────────────────────────────────────────────
            if user.role == "student":
                student = await Student.find_one(
                    Student.user_id == user.id,
                    *([Student.college_id == col_id] if col_id else [])
                )
                if student:
                    context.update({
                        "roll_no": student.roll_no,
                        "department": student.department,
                        "year": student.year,
                        "semester": student.semester,
                    })

                    # Results — scoped by student document id and user id
                    results = await Result.find(
                        Result.student_id == student.id
                    ).limit(10).to_list()
                    if not results:
                        results = await Result.find(
                            Result.student_id == user.id
                        ).limit(10).to_list()
                    context["results"] = [
                        {
                            "subject": r.subject,
                            "exam_name": r.exam_name or "Internal Exam",
                            "total_marks": r.total_marks,
                            "grade": r.grade,
                        }
                        for r in results
                    ]

                    # Attendance — FIX: filter by college_id
                    if col_id:
                        attendances = await Attendance.find(
                            Attendance.college_id == col_id
                        ).limit(100).to_list()
                    else:
                        attendances = []

                    total_classes = 0
                    present_count = 0
                    student_records = []
                    for att in attendances:
                        for rec in att.records:
                            if str(rec.student_id) in (str(student.id), str(user.id)):
                                total_classes += 1
                                if rec.status in ("present", "late"):
                                    present_count += 1
                                student_records.append({
                                    "subject": att.subject,
                                    "date": att.date.strftime("%Y-%m-%d") if att.date else "",
                                    "status": rec.status,
                                })
                    pct = round((present_count / total_classes * 100), 1) if total_classes > 0 else 100.0
                    context["attendance_summary"] = {
                        "total_classes": total_classes,
                        "present": present_count,
                        "percentage": pct,
                        "records": student_records[:5],
                    }

                    # Assignments — college-scoped published only
                    if col_id:
                        assignments = await Assignment.find(
                            Assignment.college_id == col_id,
                            Assignment.published == True,
                        ).limit(10).to_list()
                        context["assignments"] = [
                            {
                                "title": a.title,
                                "subject": a.subject or "General",
                                "due_date": a.due_date.strftime("%Y-%m-%d") if a.due_date else "No deadline",
                            }
                            for a in assignments
                        ]

                    # Timetable count
                    if col_id:
                        tt_count = await TimetableEntry.find(
                            TimetableEntry.college_id == col_id
                        ).count()
                        context["timetable_count"] = tt_count

            # ── FACULTY ────────────────────────────────────────────────────────
            elif user.role == "faculty":
                faculty = await Faculty.find_one(
                    Faculty.user_id == user.id,
                    *([Faculty.college_id == col_id] if col_id else [])
                )
                if faculty:
                    context.update({
                        "department": faculty.department,
                        "designation": faculty.designation or "Faculty Member",
                        "subjects": faculty.subjects,
                        "assigned_students_count": len(faculty.student_ids),
                    })

                    created_count = await Assignment.find(
                        Assignment.created_by == user.id
                    ).count()
                    context["created_assignments_count"] = created_count

                    my_tt = await TimetableEntry.find(
                        TimetableEntry.faculty_id == user.id
                    ).limit(20).to_list()
                    context["timetable_sessions"] = [
                        {
                            "subject": t.subject,
                            "classroom": t.classroom or "N/A",
                            "day": t.day_of_week,
                            "time": f"{t.start_time} - {t.end_time}",
                        }
                        for t in my_tt
                    ]

            # ── PARENT ─────────────────────────────────────────────────────────
            elif user.role == "parent":
                child_user_ids = user.profile.student_ids if user.profile else []
                children_info = []
                for cid_str in child_user_ids:
                    try:
                        cid = PydanticObjectId(str(cid_str))
                        c_user = await User.get(cid)
                        c_student = await Student.find_one(Student.user_id == cid)
                        if c_user:
                            results = await Result.find(
                                Result.student_id == (c_student.id if c_student else cid)
                            ).limit(5).to_list()
                            children_info.append({
                                "name": c_user.name,
                                "roll_no": c_student.roll_no if c_student else "N/A",
                                "department": c_student.department if c_student else "N/A",
                                "year": c_student.year if c_student else 1,
                                "results_count": len(results),
                            })
                    except Exception:
                        pass
                context["children"] = children_info

            # ── ADMIN ──────────────────────────────────────────────────────────
            elif user.role in ("college_admin", "super_admin"):
                if col_id:
                    context["total_students"] = await Student.find(
                        Student.college_id == col_id
                    ).count()
                    context["total_faculty"] = await Faculty.find(
                        Faculty.college_id == col_id
                    ).count()
                    context["total_assignments"] = await Assignment.find(
                        Assignment.college_id == col_id
                    ).count()
                elif user.role == "super_admin":
                    context["total_colleges"] = await College.find().count()
                    context["total_users"] = await User.find().count()

            # ── WARDEN ─────────────────────────────────────────────────────────
            elif user.role == "warden":
                if col_id:
                    rooms = await Room.find(Room.college_id == col_id).to_list()
                    outpasses = await Outpass.find(Outpass.college_id == col_id).to_list()
                    pending_outpasses = [o for o in outpasses if o.status == "pending"]
                    context.update({
                        "total_rooms": len(rooms),
                        "total_capacity": sum(r.capacity for r in rooms),
                        "total_occupied": sum(r.occupied for r in rooms),
                        "pending_outpasses_count": len(pending_outpasses),
                    })

        except Exception as e:
            logger.error(f"Error gathering AI context for {user.role} user {user.id}: {e}")

        return context

    # ── Main Chat Processor ─────────────────────────────────────────────────────

    @classmethod
    async def process_chat(
        cls,
        user: User,
        college: Optional[College],
        user_message: str,
        image_base64: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process an AI chat request with live context and conversation memory."""
        if not user_message.strip() and not image_base64:
            raise ValueError("Message cannot be empty")

        # 1. Gather live MongoDB context for the user
        context = await cls.gather_user_context(user, college)

        # 2. Retrieve recent history for memory (limit to avoid token overflow)
        recent_history = await cls.get_chat_history(user.id, limit=HISTORY_CONTEXT_LIMIT)

        # 3. Compose message content; if image provided, note it in the message
        col_id = college.id if college else user.college_id
        full_message = user_message
        if image_base64:
            full_message = f"[Image attached]\n{user_message}" if user_message.strip() else "[Image attached — please analyze this image]"

        # 4. Save user message
        await cls.save_message(
            user_id=user.id,
            college_id=col_id,
            role=user.role,
            sender="user",
            content=full_message,
        )

        # 5. Generate AI response
        response_text = await cls._generate_response(
            user=user,
            college=college,
            context=context,
            history=recent_history,
            user_message=user_message,
            image_base64=image_base64,
        )

        # 6. Save assistant response
        await cls.save_message(
            user_id=user.id,
            college_id=col_id,
            role=user.role,
            sender="assistant",
            content=response_text,
        )

        return {
            "reply": response_text,
            "suggested_questions": cls.get_role_suggestions(user.role),
        }

    # ── LLM Cascade ─────────────────────────────────────────────────────────────

    @classmethod
    async def _generate_response(
        cls,
        user: User,
        college: Optional[College],
        context: Dict[str, Any],
        history: List[AiChatMessage],
        user_message: str,
        image_base64: Optional[str] = None,
    ) -> str:
        # Groq first (fastest, free tier available)
        if settings.GROQ_API_KEY:
            try:
                reply = await cls._call_groq_api(user_message, history, context, image_base64)
                if reply:
                    return reply
            except Exception as e:
                logger.warning(f"Groq API failed: {e}")

        # Gemini second (supports vision natively)
        if settings.GEMINI_API_KEY:
            try:
                reply = await cls._call_gemini_api(user_message, history, context, image_base64)
                if reply:
                    return reply
            except Exception as e:
                logger.warning(f"Gemini API failed: {e}")

        # OpenAI fallback
        if settings.OPENAI_API_KEY:
            try:
                reply = await cls._call_openai_api(user_message, history, context, image_base64)
                if reply:
                    return reply
            except Exception as e:
                logger.warning(f"OpenAI API failed: {e}")

        # Smart keyword fallback (no LLM required)
        return cls._smart_domain_response(user, context, user_message)

    @classmethod
    async def _call_groq_api(
        cls,
        prompt: str,
        history: List[AiChatMessage],
        context: Dict[str, Any],
        image_base64: Optional[str] = None,
    ) -> Optional[str]:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        system_prompt = (
            f"You are CampusOS AI Assistant helping '{context.get('user_name')}' "
            f"({context.get('role')} at {context.get('college_name')}). "
            f"Live campus data: {context}. "
            "Respond in a helpful, concise, markdown-formatted manner. "
            "Prioritize data from the live context provided."
        )

        messages = [{"role": "system", "content": system_prompt}]
        for msg in history[-HISTORY_CONTEXT_LIMIT:]:
            messages.append({
                "role": "user" if msg.sender == "user" else "assistant",
                "content": msg.content,
            })

        # Groq does not yet support vision; send text-only even if image provided
        user_content = prompt
        if image_base64:
            user_content = f"[The user has uploaded an image. Describe what a campus AI would say about it.]\n{prompt}"
        messages.append({"role": "user", "content": user_content})

        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1024,
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.post(url, json=payload, headers=headers)
            if res.status_code == 200:
                return res.json()["choices"][0]["message"]["content"]
            logger.warning(f"Groq HTTP {res.status_code}: {res.text[:200]}")
        return None

    @classmethod
    async def _call_gemini_api(
        cls,
        prompt: str,
        history: List[AiChatMessage],
        context: Dict[str, Any],
        image_base64: Optional[str] = None,
    ) -> Optional[str]:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-1.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
        )
        system_instruction = (
            f"You are the CampusOS AI Assistant for '{context.get('user_name')}' "
            f"({context.get('role')} at {context.get('college_name')}). "
            f"Live campus data context: {context}. "
            "Be concise, accurate, and format responses in markdown."
        )

        hist_str = "\n".join([f"{m.sender.upper()}: {m.content}" for m in history[-HISTORY_CONTEXT_LIMIT:]])
        full_text = f"{system_instruction}\n\nConversation:\n{hist_str}\n\nUser: {prompt}"

        # Build content parts — support vision if image provided
        parts: list = [{"text": full_text}]
        if image_base64:
            # Strip data URI prefix if present
            img_data = image_base64
            if "," in image_base64:
                img_data = image_base64.split(",", 1)[1]
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": img_data,
                }
            })

        payload = {"contents": [{"parts": parts}]}

        async with httpx.AsyncClient(timeout=25.0) as client:
            res = await client.post(url, json=payload)
            if res.status_code == 200:
                data = res.json()
                try:
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError):
                    return None
            logger.warning(f"Gemini HTTP {res.status_code}: {res.text[:200]}")
        return None

    @classmethod
    async def _call_openai_api(
        cls,
        prompt: str,
        history: List[AiChatMessage],
        context: Dict[str, Any],
        image_base64: Optional[str] = None,
    ) -> Optional[str]:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        system_prompt = (
            f"You are CampusOS AI Assistant for '{context.get('user_name')}' "
            f"({context.get('role')} at {context.get('college_name')}). "
            f"Live data: {context}. Reply concisely in markdown."
        )

        messages = [{"role": "system", "content": system_prompt}]
        for msg in history[-HISTORY_CONTEXT_LIMIT:]:
            messages.append({
                "role": "user" if msg.sender == "user" else "assistant",
                "content": msg.content,
            })

        # Vision support via gpt-4o if image provided
        if image_base64:
            img_data = image_base64
            if "," in image_base64:
                img_data = image_base64.split(",", 1)[1]
            model = "gpt-4o"
            user_content: Any = [
                {"type": "text", "text": prompt or "Please analyze this image."},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_data}"},
                },
            ]
        else:
            model = "gpt-3.5-turbo"
            user_content = prompt

        messages.append({"role": "user", "content": user_content})

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": 1024,
        }

        async with httpx.AsyncClient(timeout=25.0) as client:
            res = await client.post(url, json=payload, headers=headers)
            if res.status_code == 200:
                return res.json()["choices"][0]["message"]["content"]
            logger.warning(f"OpenAI HTTP {res.status_code}: {res.text[:200]}")
        return None

    # ── Smart Keyword Fallback ───────────────────────────────────────────────────

    @classmethod
    def _smart_domain_response(cls, user: User, context: Dict[str, Any], query: str) -> str:
        q = query.lower()
        role = user.role
        name = user.name

        # ── STUDENT ────────────────────────────────────────────────────────────
        if role == "student":
            if "attendance" in q:
                summary = context.get("attendance_summary", {})
                pct = summary.get("percentage", 100.0)
                tot = summary.get("total_classes", 0)
                prs = summary.get("present", 0)
                status_str = "✅ Good Standing" if pct >= 75 else "⚠️ Below Required Minimum"
                return (
                    f"### 📊 Attendance Report for {name}\n\n"
                    f"- **Overall Attendance:** `{pct}%` — {status_str}\n"
                    f"- **Sessions Present:** {prs} / {tot} total classes\n\n"
                    f"_(Campus policy requires minimum **75% attendance** for exam eligibility.)_"
                )
            elif any(k in q for k in ("result", "grade", "marks", "score")):
                results = context.get("results", [])
                if not results:
                    return (
                        f"### 📝 Exam Results — {name}\n\n"
                        f"No published scores found for Semester {context.get('semester', 1)}. "
                        f"Check back once faculty publish grades."
                    )
                lines = "\n".join(
                    f"- **{r['subject']}**: `{r.get('total_marks', 'N/A')}` marks — Grade `{r.get('grade', 'N/A')}` ({r.get('exam_name', 'Exam')})"
                    for r in results
                )
                return f"### 📝 Academic Performance\n\n{lines}\n\nView full marksheet in the **Results** section."
            elif any(k in q for k in ("assignment", "homework", "task")):
                assignments = context.get("assignments", [])
                if not assignments:
                    return "### 📚 Assignments\n\nNo pending published assignments right now! 🎉"
                lines = "\n".join(
                    f"- 📌 **{a['title']}** ({a['subject']}) — Due: `{a['due_date']}`"
                    for a in assignments
                )
                return f"### 📚 Active Assignments\n\n{lines}\n\nSubmit via the **Assignments** tab."
            elif any(k in q for k in ("timetable", "schedule", "class", "today")):
                return (
                    f"### 📅 Timetable — {context.get('department', 'Engineering')} Sem {context.get('semester', 1)}\n\n"
                    f"Your weekly schedule is active. Visit the **Timetable** section for session times and rooms."
                )
            elif any(k in q for k in ("fee", "dues", "payment")):
                return (
                    f"### 💳 Fee Status\n\n"
                    f"- **Roll No:** `{context.get('roll_no', 'N/A')}`\n"
                    f"- Contact the admin office for official receipts or fee structure queries.\n"
                    f"- Check the **Fees** section for your current balance and due dates."
                )
            elif any(k in q for k in ("study", "help", "prepare", "exam")):
                return (
                    f"### 💡 Study Assistance for {name}\n\n"
                    f"1. **Review lecture notes** published in the Notes section.\n"
                    f"2. **Complete assignments** to reinforce key concepts.\n"
                    f"3. **Maintain 80%+ attendance** — it directly impacts grades.\n"
                    f"4. **Collaborate with peers** on practical assignments."
                )

        # ── FACULTY ────────────────────────────────────────────────────────────
        elif role == "faculty":
            if any(k in q for k in ("student", "performance", "class")):
                count = context.get("assigned_students_count", 0)
                dept = context.get("department", "Department")
                return (
                    f"### 👨‍🏫 Faculty Insights\n\n"
                    f"- **Department:** {dept}\n"
                    f"- **Assigned Students:** `{count}`\n"
                    f"- **Subjects:** {', '.join(context.get('subjects', ['General']))}\n\n"
                    f"View individual student scores in the **Students** section."
                )
            elif "attendance" in q:
                return (
                    f"### 📋 Attendance Management\n\n"
                    f"Record daily attendance, mark statuses, and export logs from the **Attendance** tab."
                )
            elif any(k in q for k in ("assignment", "grading", "evaluation")):
                return (
                    f"### 📝 Assignments & Grading\n\n"
                    f"- **Published:** `{context.get('created_assignments_count', 0)}`\n\n"
                    f"Evaluate submissions and post grades via the **Assignments** menu."
                )

        # ── PARENT ─────────────────────────────────────────────────────────────
        elif role == "parent":
            if any(k in q for k in ("attendance", "child", "student", "result", "performance")):
                children = context.get("children", [])
                if children:
                    lines = "\n".join(
                        f"- 👤 **{c['name']}** (Roll: {c['roll_no']}, {c['department']}) — {c['results_count']} result(s)"
                        for c in children
                    )
                    return (
                        f"### 👨‍👩‍👧 Child Academic Overview\n\n{lines}\n\n"
                        f"Track attendance and exams under **My Children** → **Results**."
                    )
                return (
                    f"### 👨‍👩‍👧 Child Progress\n\n"
                    f"Your account is linked to your child's record. "
                    f"Go to **My Children** to review marks and attendance."
                )
            elif any(k in q for k in ("notification", "notice")):
                return "### 🔔 Notifications\n\nCheck official announcements in the **Notifications** tab."
            elif any(k in q for k in ("fee", "payment")):
                return (
                    f"### 💳 Fee Status\n\n"
                    f"Contact the college office for receipt copies. "
                    f"Check the **Fees** section for current dues."
                )

        # ── ADMIN ──────────────────────────────────────────────────────────────
        elif role in ("college_admin", "super_admin"):
            if any(k in q for k in ("stat", "insight", "report", "summary", "user")):
                if "total_students" in context:
                    return (
                        f"### 🏛️ College Statistics\n\n"
                        f"- **Institution:** {context.get('college_name')}\n"
                        f"- **Students:** `{context.get('total_students', 0)}`\n"
                        f"- **Faculty:** `{context.get('total_faculty', 0)}`\n"
                        f"- **Assignments:** `{context.get('total_assignments', 0)}`\n\n"
                        f"Manage accounts via **Students** and **Faculty** dashboards."
                    )
                return (
                    f"### 🌐 Platform Overview\n\n"
                    f"- **Colleges:** `{context.get('total_colleges', 0)}`\n"
                    f"- **Users:** `{context.get('total_users', 0)}`\n\n"
                    f"Onboard new tenants from the **Colleges** tab."
                )

        # ── WARDEN ─────────────────────────────────────────────────────────────
        elif role == "warden":
            if any(k in q for k in ("hostel", "room", "occupancy", "outpass", "record")):
                return (
                    f"### 🏨 Hostel Summary\n\n"
                    f"- **Rooms:** `{context.get('total_rooms', 0)}`\n"
                    f"- **Occupied:** `{context.get('total_occupied', 0)} / {context.get('total_capacity', 0)}`\n"
                    f"- **Pending Outpasses:** `{context.get('pending_outpasses_count', 0)}`\n\n"
                    f"Manage outpass requests in the **Outpasses** dashboard."
                )

        # ── DEFAULT ────────────────────────────────────────────────────────────
        return (
            f"Hello **{name}**! I am your **CampusOS AI Assistant** 🤖\n\n"
            f"I am configured for your role as **{role.replace('_', ' ').title()}** "
            f"at **{context.get('college_name')}**.\n\n"
            f"You can ask me about:\n"
            f"- Academic records, attendance, results, assignments\n"
            f"- Timetable, fee status, notifications\n"
            f"- Hostel, outpasses, student management\n\n"
            f"_Tip: Use the suggestion chips below for quick questions!_"
        )

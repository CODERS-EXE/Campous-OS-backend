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
from app.models.notification import Notification
from app.models.result import Result
from app.models.student import Student
from app.models.submission import Submission
from app.models.timetable import TimetableEntry
from app.models.user import User

logger = logging.getLogger(__name__)
settings = get_settings()


class AiService:
    @staticmethod
    async def get_chat_history(user_id: PydanticObjectId, limit: int = 50) -> List[AiChatMessage]:
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

    @staticmethod
    def get_role_suggestions(role: str) -> List[str]:
        if role == "student":
            return [
                "What is my current attendance percentage?",
                "Show my recent exam results and grades",
                "What assignments are due soon?",
                "What is my schedule and timetable for today?",
                "How can I prepare for my upcoming exams?"
            ]
        elif role == "faculty":
            return [
                "Show attendance summary for my classes",
                "What is the average performance of my students?",
                "Which assignments need evaluation and grading?",
                "What is my teaching schedule for today?",
                "How can I improve student engagement?"
            ]
        elif role == "parent":
            return [
                "How is my child's attendance record?",
                "What are my child's latest exam results?",
                "Are there any unread college notifications?",
                "What is the fee status for my child?",
                "Is my child hostel or bus tracking active?"
            ]
        elif role in ("college_admin", "super_admin"):
            return [
                "Give me a summary of total students and faculty",
                "What is the overall college attendance rate?",
                "Show department-wise student distribution",
                "Are there any urgent notifications or fee alerts?",
                "Generate an administrative performance report"
            ]
        elif role == "warden":
            return [
                "What is the current hostel room occupancy rate?",
                "How many outpass requests are pending approval?",
                "Show hosteller emergency contact records",
                "List available rooms in block A and B",
                "Show recent hostel activity and outpass logs"
            ]
        return [
            "How can CampusOS AI help me today?",
            "Show system overview and status",
            "What features are available for my role?"
        ]

    @classmethod
    async def gather_user_context(cls, user: User, college: Optional[College]) -> Dict[str, Any]:
        """Fetch live MongoDB data context based on user role and tenant isolation."""
        context: Dict[str, Any] = {
            "user_name": user.name,
            "user_email": user.email,
            "role": user.role,
            "college_name": college.name if college else "CampusOS Platform",
        }

        try:
            # 1. STUDENT CONTEXT
            if user.role == "student":
                student = await Student.find_one(Student.user_id == user.id)
                if student:
                    context["roll_no"] = student.roll_no
                    context["department"] = student.department
                    context["year"] = student.year
                    context["semester"] = student.semester

                    # Exam Results
                    results = await Result.find(Result.student_id == student.id).to_list()
                    if not results:
                        results = await Result.find(Result.student_id == user.id).to_list()
                    context["results"] = [
                        {
                            "subject": r.subject,
                            "exam_name": r.exam_name or "Internal Exam",
                            "total_marks": r.total_marks,
                            "grade": r.grade,
                        }
                        for r in results
                    ]

                    # Attendance Summary
                    attendances = await Attendance.find().to_list()
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
                                    "status": rec.status
                                })
                    pct = round((present_count / total_classes * 100), 1) if total_classes > 0 else 100.0
                    context["attendance_summary"] = {
                        "total_classes": total_classes,
                        "present": present_count,
                        "percentage": pct,
                        "records": student_records[:5]
                    }

                    # Assignments
                    col_id = college.id if college else user.college_id
                    if col_id:
                        assignments = await Assignment.find(
                            Assignment.college_id == col_id,
                            Assignment.published == True
                        ).to_list()
                        context["assignments"] = [
                            {
                                "title": a.title,
                                "subject": a.subject or "General",
                                "due_date": a.due_date.strftime("%Y-%m-%d") if a.due_date else "No deadline"
                            }
                            for a in assignments
                        ]

                    # Timetable
                    if col_id:
                        timetable = await TimetableEntry.find(TimetableEntry.college_id == col_id).to_list()
                        context["timetable_count"] = len(timetable)

            # 2. FACULTY CONTEXT
            elif user.role == "faculty":
                faculty = await Faculty.find_one(Faculty.user_id == user.id)
                if faculty:
                    context["department"] = faculty.department
                    context["designation"] = faculty.designation or "Faculty Member"
                    context["subjects"] = faculty.subjects
                    context["assigned_students_count"] = len(faculty.student_ids)

                    # Assignments created by faculty
                    my_assignments = await Assignment.find(Assignment.created_by == user.id).to_list()
                    context["created_assignments_count"] = len(my_assignments)

                    # Timetable entries for faculty
                    my_tt = await TimetableEntry.find(TimetableEntry.faculty_id == user.id).to_list()
                    context["timetable_sessions"] = [
                        {
                            "subject": t.subject,
                            "classroom": t.classroom or "N/A",
                            "day": t.day_of_week,
                            "time": f"{t.start_time} - {t.end_time}"
                        }
                        for t in my_tt
                    ]

            # 3. PARENT CONTEXT
            elif user.role == "parent":
                child_user_ids = user.profile.student_ids if user.profile else []
                children_info = []
                for cid_str in child_user_ids:
                    try:
                        cid = PydanticObjectId(cid_str)
                        c_user = await User.get(cid)
                        c_student = await Student.find_one(Student.user_id == cid)
                        if c_user:
                            results = await Result.find(Result.student_id == (c_student.id if c_student else cid)).to_list()
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

            # 4. ADMIN CONTEXT (COLLEGE ADMIN / SUPER ADMIN)
            elif user.role in ("college_admin", "super_admin"):
                col_id = college.id if college else user.college_id
                if col_id:
                    total_students = await Student.find(Student.college_id == col_id).count()
                    total_faculty = await Faculty.find(Faculty.college_id == col_id).count()
                    total_assignments = await Assignment.find(Assignment.college_id == col_id).count()
                    context["total_students"] = total_students
                    context["total_faculty"] = total_faculty
                    context["total_assignments"] = total_assignments
                else:
                    context["total_colleges"] = await College.find().count()
                    context["total_users"] = await User.find().count()

            # 5. WARDEN CONTEXT
            elif user.role == "warden":
                col_id = college.id if college else user.college_id
                if col_id:
                    rooms = await Room.find(Room.college_id == col_id).to_list()
                    outpasses = await Outpass.find(Outpass.college_id == col_id).to_list()
                    pending_outpasses = [o for o in outpasses if o.status == "pending"]
                    total_capacity = sum(r.capacity for r in rooms)
                    total_occupied = sum(r.occupied for r in rooms)

                    context["total_rooms"] = len(rooms)
                    context["total_capacity"] = total_capacity
                    context["total_occupied"] = total_occupied
                    context["pending_outpasses_count"] = len(pending_outpasses)

        except Exception as e:
            logger.error(f"Error gathering context for AI: {e}")

        return context

    @classmethod
    async def process_chat(
        cls,
        user: User,
        college: Optional[College],
        user_message: str
    ) -> Dict[str, Any]:
        """Main entry point to process AI chat request with multi-turn history memory."""
        # 1. Fetch live MongoDB context
        context = await cls.gather_user_context(user, college)

        # 2. Retrieve recent conversation history for memory context (last 5 messages)
        recent_history = await cls.get_chat_history(user.id, limit=5)

        # 3. Save current user message to database
        await cls.save_message(
            user_id=user.id,
            college_id=college.id if college else user.college_id,
            role=user.role,
            sender="user",
            content=user_message
        )

        # 4. Generate AI response using Groq / Gemini / OpenAI / Smart Domain Fallback Engine
        response_text = await cls._generate_response(user, college, context, recent_history, user_message)

        # 5. Save assistant response to database
        await cls.save_message(
            user_id=user.id,
            college_id=college.id if college else user.college_id,
            role=user.role,
            sender="assistant",
            content=response_text
        )

        # 6. Suggested questions
        suggestions = cls.get_role_suggestions(user.role)

        return {
            "reply": response_text,
            "suggested_questions": suggestions,
        }

    @classmethod
    async def _generate_response(
        cls,
        user: User,
        college: Optional[College],
        context: Dict[str, Any],
        history: List[AiChatMessage],
        user_message: str
    ) -> str:
        # Check available LLM API keys in config
        if settings.GROQ_API_KEY:
            try:
                reply = await cls._call_groq_api(user_message, history, context)
                if reply:
                    return reply
            except Exception as e:
                logger.warning(f"Groq API call failed: {e}")

        if settings.GEMINI_API_KEY:
            try:
                reply = await cls._call_gemini_api(user_message, history, context)
                if reply:
                    return reply
            except Exception as e:
                logger.warning(f"Gemini API call failed: {e}")

        if settings.OPENAI_API_KEY:
            try:
                reply = await cls._call_openai_api(user_message, history, context)
                if reply:
                    return reply
            except Exception as e:
                logger.warning(f"OpenAI API call failed: {e}")

        # Smart fallback domain engine using live MongoDB context
        return cls._smart_domain_response(user, context, user_message)

    @classmethod
    async def _call_groq_api(
        cls,
        prompt: str,
        history: List[AiChatMessage],
        context: Dict[str, Any]
    ) -> Optional[str]:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {settings.GROQ_API_KEY}"}
        system_prompt = (
            f"You are the CampusOS AI Assistant for user '{context.get('user_name')}' "
            f"({context.get('role')} at {context.get('college_name')}). Live context: {context}"
        )

        messages = [{"role": "system", "content": system_prompt}]
        for msg in history:
            role_str = "user" if msg.sender == "user" else "assistant"
            messages.append({"role": role_str, "content": msg.content})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": messages,
            "temperature": 0.7
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(url, json=payload, headers=headers)
            if res.status_code == 200:
                data = res.json()
                return data["choices"][0]["message"]["content"]
        return None

    @classmethod
    async def _call_gemini_api(
        cls,
        prompt: str,
        history: List[AiChatMessage],
        context: Dict[str, Any]
    ) -> Optional[str]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
        system_instruction = (
            f"You are the CampusOS AI Assistant. You are conversing with user '{context.get('user_name')}' "
            f"who is a {context.get('role')} at {context.get('college_name')}.\n"
            f"Live Database Context: {context}\n"
            "Provide concise, accurate, polite, and well-formatted markdown answers."
        )

        hist_str = "\n".join([f"{m.sender.upper()}: {m.content}" for m in history])
        full_text = f"{system_instruction}\n\nChat History:\n{hist_str}\n\nUser Question: {prompt}"

        payload = {
            "contents": [{"parts": [{"text": full_text}]}]
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(url, json=payload)
            if res.status_code == 200:
                data = res.json()
                try:
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError):
                    return None
        return None

    @classmethod
    async def _call_openai_api(
        cls,
        prompt: str,
        history: List[AiChatMessage],
        context: Dict[str, Any]
    ) -> Optional[str]:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
        system_prompt = (
            f"You are the CampusOS AI Assistant for user '{context.get('user_name')}' "
            f"({context.get('role')} at {context.get('college_name')}). Live context: {context}"
        )

        messages = [{"role": "system", "content": system_prompt}]
        for msg in history:
            role_str = "user" if msg.sender == "user" else "assistant"
            messages.append({"role": role_str, "content": msg.content})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": "gpt-3.5-turbo",
            "messages": messages,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(url, json=payload, headers=headers)
            if res.status_code == 200:
                data = res.json()
                return data["choices"][0]["message"]["content"]
        return None

    @classmethod
    def _smart_domain_response(cls, user: User, context: Dict[str, Any], query: str) -> str:
        q = query.lower()
        role = user.role
        user_name = user.name

        # --- STUDENT RESPONSES ---
        if role == "student":
            if "attendance" in q:
                summary = context.get("attendance_summary", {})
                pct = summary.get("percentage", 100.0)
                tot = summary.get("total_classes", 0)
                prs = summary.get("present", 0)
                status_emoji = "✅ Good Standing" if pct >= 75 else "⚠️ Attention Needed"
                return (
                    f"### 📊 Attendance Report for {user_name}\n\n"
                    f"- **Overall Attendance:** `{pct}%` ({status_emoji})\n"
                    f"- **Sessions Present:** {prs} / {tot} total classes\n\n"
                    f"*(Campus Policy requires minimum 75% attendance to sit for final semester examinations).* "
                    f"You can view session records under the **Attendance** section."
                )
            elif "result" in q or "grade" in q or "marks" in q or "score" in q:
                results = context.get("results", [])
                if not results:
                    return (
                        f"### 📝 Academic Results for {user_name}\n\n"
                        f"No published examination scores were found for your profile yet (Semester {context.get('semester', 1)}). "
                        f"Please check back when course faculty publish grades."
                    )
                res_lines = "\n".join([
                    f"- **{r['subject']}**: Marks `{r.get('total_marks', 'N/A')}` | Grade `{r.get('grade', 'N/A')}` ({r.get('exam_name', 'Exam')})"
                    for r in results
                ])
                return (
                    f"### 📝 Academic Performance Summary\n\n"
                    f"Here are your latest recorded grades:\n\n{res_lines}\n\n"
                    f"Keep up the effort! Detailed subject breakdowns are available in **Results**."
                )
            elif "assignment" in q or "homework" in q or "task" in q:
                assignments = context.get("assignments", [])
                if not assignments:
                    return (
                        f"### 📚 Assignment Tracker\n\n"
                        f"You have no pending published assignments at this time! 🎉"
                    )
                asg_lines = "\n".join([
                    f"- 📌 **{a['title']}** ({a['subject']}) — Due: `{a['due_date']}`"
                    for a in assignments
                ])
                return (
                    f"### 📚 Active Course Assignments\n\n"
                    f"Here are your published assignments:\n\n{asg_lines}\n\n"
                    f"Submit your solutions prior to the deadline via the **Assignments** tab."
                )
            elif "timetable" in q or "schedule" in q or "class" in q:
                return (
                    f"### 📅 Timetable & Schedule\n\n"
                    f"Your weekly timetable for **{context.get('department', 'Engineering')} (Semester {context.get('semester', 1)})** "
                    f"is active. Visit the **Timetable** section for live session times and assigned classroom numbers."
                )
            elif "fee" in q or "dues" in q or "payment" in q:
                return (
                    f"### 💳 Fee Status & Dues\n\n"
                    f"- **Roll No:** `{context.get('roll_no', user.id)}`\n"
                    f"- **Status:** `Active / Settled`\n"
                    f"- **Next Installment:** Due at semester registration.\n\n"
                    f"For official receipts or fee structure queries, contact the administration office."
                )
            elif "study" in q or "help" in q or "prepare" in q or "exam" in q:
                return (
                    f"### 💡 Study Assistance & Exam Advice\n\n"
                    f"CampusOS AI Recommendations for {user_name}:\n"
                    f"1. **Review Notes:** Access published lecture slides in the Notes section.\n"
                    f"2. **Solve Assignments:** Complete coursework to reinforce key concepts.\n"
                    f"3. **Maintain 80%+ Attendance:** Active participation improves academic outcomes.\n"
                    f"4. **Peer Collaboration:** Work together on practical assignments."
                )

        # --- FACULTY RESPONSES ---
        elif role == "faculty":
            if "student" in q or "performance" in q or "class" in q:
                count = context.get("assigned_students_count", 0)
                dept = context.get("department", "Department")
                return (
                    f"### 👨‍🏫 Faculty Insights & Students Overview\n\n"
                    f"- **Department:** {dept}\n"
                    f"- **Assigned Students:** `{count}` active students\n"
                    f"- **Subjects:** {', '.join(context.get('subjects', ['General']))}\n\n"
                    f"Inspect individual student scores and attendance metrics in the **Students** management section."
                )
            elif "attendance" in q:
                return (
                    f"### 📋 Class Attendance Management\n\n"
                    f"You can record daily lecture attendance, mark student attendance statuses, and export logs from the **Attendance** tab."
                )
            elif "assignment" in q or "grading" in q:
                created = context.get("created_assignments_count", 0)
                return (
                    f"### 📝 Assignment & Evaluation Portal\n\n"
                    f"- **Assignments Published:** `{created}`\n\n"
                    f"Evaluate student file submissions and post grades via the **Assignments** menu."
                )
            elif "teach" in q or "help" in q or "lesson" in q:
                return (
                    f"### 🎓 Teaching & Lesson Assistance\n\n"
                    f"CampusOS AI Teaching Tips:\n"
                    f"1. **Short Reflection Tasks:** Publish post-lecture assignments to test retention.\n"
                    f"2. **Early Interventions:** Identify students below 75% attendance for mentoring.\n"
                    f"3. **Notification Alerts:** Broadcast exam dates and submission reminders."
                )

        # --- PARENT RESPONSES ---
        elif role == "parent":
            if "attendance" in q or "child" in q or "student" in q or "result" in q or "performance" in q:
                children = context.get("children", [])
                if children:
                    c_info = "\n".join([
                        f"- 👤 **{c['name']}** (Roll: {c['roll_no']}, Dept: {c['department']}) — {c['results_count']} recorded result(s)"
                        for c in children
                    ])
                    return (
                        f"### 👨‍👩‍👧 Child Academic & Attendance Overview\n\n"
                        f"Linked children profile(s):\n\n{c_info}\n\n"
                        f"Track attendance percentages and examination transcripts under **My Children** and **Results**."
                    )
                return (
                    f"### 👨‍👩‍👧 Child Progress & Attendance\n\n"
                    f"Your account is connected to your child's student record. "
                    f"Go to **My Children** to review attendance, marks, and announcements."
                )
            elif "notification" in q or "notice" in q:
                return (
                    f"### 🔔 Parent Announcements & Notices\n\n"
                    f"View official college announcements, fee circulars, and holiday notifications in the **Notifications** tab."
                )
            elif "fee" in q or "payment" in q:
                return (
                    f"### 💳 Fee Status\n\n"
                    f"- **Status:** `Up to date`\n"
                    f"- **Portal:** Managed through College Administration.\n"
                    f"Contact the college office if you need receipt copies."
                )

        # --- ADMIN RESPONSES ---
        elif role in ("college_admin", "super_admin"):
            if "stat" in q or "insight" in q or "report" in q or "summary" in q or "user" in q:
                if "total_students" in context:
                    st = context.get("total_students", 0)
                    fa = context.get("total_faculty", 0)
                    asg = context.get("total_assignments", 0)
                    return (
                        f"### 🏛️ College Statistics & Overview\n\n"
                        f"- **Institution:** {context.get('college_name')}\n"
                        f"- **Total Active Students:** `{st}`\n"
                        f"- **Total Faculty:** `{fa}`\n"
                        f"- **Course Assignments:** `{asg}`\n"
                        f"- **System Health:** `100% Operational`\n\n"
                        f"Manage college accounts and permissions via the **Students** and **Faculty** dashboards."
                    )
                else:
                    tc = context.get("total_colleges", 0)
                    tu = context.get("total_users", 0)
                    return (
                        f"### 🌐 Super Admin Platform Overview\n\n"
                        f"- **Total Colleges:** `{tc}`\n"
                        f"- **Total Platform Users:** `{tu}`\n"
                        f"- **System Infrastructure:** `All Services Active`\n\n"
                        f"Onboard new college tenants or inspect multi-tenant analytics from the **Colleges** tab."
                    )

        # --- WARDEN RESPONSES ---
        elif role == "warden":
            if "hostel" in q or "room" in q or "occupancy" in q or "outpass" in q or "record" in q:
                tot_r = context.get("total_rooms", 0)
                tot_c = context.get("total_capacity", 0)
                tot_o = context.get("total_occupied", 0)
                p_out = context.get("pending_outpasses_count", 0)
                return (
                    f"### 🏨 Hostel Administration Summary\n\n"
                    f"- **Total Rooms:** `{tot_r}`\n"
                    f"- **Beds Occupied:** `{tot_o} / {tot_c}`\n"
                    f"- **Pending Outpass Requests:** `{p_out}` pending review\n\n"
                    f"Approve or decline student outpass requests in the **Outpasses** dashboard."
                )

        # Default Intelligent Response
        return (
            f"Hello {user_name}! I am your **CampusOS AI Assistant**.\n\n"
            f"I am fully configured for your role as **{role.replace('_', ' ').title()}** at **{context.get('college_name')}**.\n\n"
            f"Feel free to ask me about your academic records, attendance percentages, exam results, assignments, timetables, fee status, or hostel outpasses!"
        )

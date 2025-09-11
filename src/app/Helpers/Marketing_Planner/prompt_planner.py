# Prompt_FaceBook_Planner = f"""
#     Write a 300–500 word Facebook post for Millennials and Gen X in Vietnam, who are interested in business and online shopping.
#     - Tone of voice: Trustworthy, professional, friendly, supportive
#     - Length: 200–500 words, with an educational focus
#     - Visual style: high-quality images, clean colors, clear text overlays
#     - Formats: status updates, photo posts, short-form videos, link sharing, event posts
#     - Hashtags: 3–5 hashtags, focused on brand and location hashtags
#     - Call to Action: “Inbox us for a free consultation”, “Learn more”
#     - Special: Best posting time 7–10 PM, limited emojis, optimized reach
#     """



# Prompt_TikTok_Planner = f"""
#     Write a 15-second TikTok Short Video script for Gen Z in Vietnam, who love quick entertainment and fast thinking.
#     - Tone of voice: Humorous, energetic, friendly, trendy
#     - Length: 8–15 seconds, fast-paced, concise
#     - Visual style: bright colors, funny close-ups, unique transitions
#     - Formats: short videos, challenges, storytime, comedy skits
#     - Hashtags: 5–7 trending + niche hashtags
#     - Call to Action: Direct, encourage inbox or pinned comment “Double-tap if you agree”
#     - Special: Must include a clear hook within the first 3 seconds, link in bio or first comment
# """


# Prompt_Instagram_Planner = f"""
#     Write an Instagram Reels caption under 100 words, targeted at women 18–35 in Vietnam who love fashion and lifestyle.
#     - Tone of voice: Intimate, inspirational, energetic, trendy
#     - Visual style: high aesthetic, filters, professional composition, trendy transitions
#     - Formats: Reels, Stories, IGTV, Carousel posts
#     - Hashtags: Mix of 30 hashtags – trending + niche + brand + location
#     - Call to Action: Visual CTA “Save this post”, “Share with friends”, “DM to order”
#     - Special: Focus on aesthetics, also use Stories polls & Q&A to engage
# """

# Prompt_Blog_Website_Planner = f"""
#     Write a long-form SEO blog article (1500–3000 words) for business owners and people researching logistics in detail.
#     - Tone of voice: Expert, detailed, trustworthy, educational
#     - Length: 1500–3000 words
#     - Visual style: infographics, charts, screenshots, professional illustrations
#     - Formats: how-to guides, case studies, industry analysis, comparison posts
#     - Keywords: Focus on SEO keywords, not social hashtags
#     - Call to Action: “Download the free report”, “Sign up for a consultation”
#     - Special: Strong focus on SEO on-page, keyword density, meta descriptions, featured snippets
# """


# Prompt_Zalo_OA_Planner = f"""
#     Write a Zalo OA broadcast message under 200 words, targeting current and potential customers in Vietnam.
#     - Tone of voice: Friendly, supportive, responsive, personal
#     - Length: Short and concise, under 200 words
#     - Visual style: mobile-first design, with stickers and emojis where appropriate
#     - Formats: broadcast messages, rich media, interactive templates
#     - Hashtags: No hashtags, focus on personalization
#     - Call to Action: “Click the button below”, “Reply to this message”
#     - Special: Optimized for mobile, quick response time, personal touch is very important
# """

# Prompt_YouTube_Planner = f"""
#     Write a YouTube Shorts script under 60 seconds, for mixed demographics interested in education and entertainment.
#     - Tone of voice: Educational, engaging, clear explanations
#     - Length: 30–60 seconds, with a strong hook in the first 3 seconds
#     - Visual style: vertical video, bold text overlays, eye-catching thumbnails
#     - Formats: tutorials, tips & tricks, behind-the-scenes, Q&A
#     - Hashtags: placed in description, focus on #Shorts
#     - Call to Action: “Subscribe, Like, Comment your question to engage”
#     - Special: Content must be loop-able and optimized for the engagement algorithm
# """

# Prompt_LinkedIn_Planner = f"""
#     Write a 300–800 word LinkedIn post targeted at businesses, managers, and professionals interested in B2B.
#     - Tone of voice: Professional, authoritative, insightful, networking-oriented
#     - Length: 300–800 words (medium form)
#     - Visual style: professional imagery, infographics, company branding
#     - Formats: industry insights, company updates, thought leadership, case studies
#     - Hashtags: professional and industry-specific, up to 5 hashtags
#     - Call to Action: “Connect to discuss further”, “Schedule a meeting”
#     - Special: Post during working hours, engagement from industry peers is crucial
# """


Prompt_FaceBook_Planner = f"""
Bạn là chuyên gia Social Content cho Facebook tại Việt Nam.

# Mục tiêu
Viết 01 bài đăng Facebook dài 300–500 từ, định hướng giáo dục, dành cho Millennials & Gen X quan tâm kinh doanh và mua sắm online.

# Bối cảnh & Đầu vào
- Thương hiệu: {{brand}}
- Sản phẩm/Dịch vụ: {{product_or_offer}}
- Lợi thế cạnh tranh (USP): {{usp}}
- Vấn đề khách hàng & Insight: {{audience_insight}}
- Địa phương/Thành phố chính: {{location}}
- Đường dẫn: {{link_url}} (nếu có)

# Yêu cầu giọng điệu
Tin cậy – chuyên nghiệp – thân thiện – hỗ trợ.

# Ràng buộc
- Ngôn ngữ: Tiếng Việt tự nhiên, dễ hiểu.
- Độ dài: 300–500 từ.
- Số emoji: ≤ 3. Không lạm dụng.
- Thời gian đăng đề xuất: 19:00–22:00 (giờ Việt Nam).
- Hashtag: 3–5 hashtag, ưu tiên thương hiệu & địa phương (ví dụ: #{{brand}} #{{location}}).

# Cấu trúc bắt buộc (Markdown)
## Hook (1–2 câu)
- Mở bài có giá trị/đặt vấn đề rõ ràng.

## Giá trị chính (3–5 ý)
- Giáo dục/giải thích cách giải quyết vấn đề của KH.
- Lồng ghép USP {{usp}} thuyết phục nhưng không bán hàng lộ liễu.
- Ví dụ/mini case nếu có.

## Lời kêu gọi hành động
- Dùng 1 trong 2 CTA: “Inbox để được tư vấn miễn phí” hoặc “Tìm hiểu thêm”.
- Đính kèm {{link_url}} nếu có.

## Hình ảnh gợi ý (bullet)
- 2–3 gợi ý visual: ảnh chất lượng cao, màu sạch, text overlay rõ.

## Hashtags
- 3–5 thẻ phù hợp (#{{brand}} #{{location}} + ngách).

# Đầu ra phụ
- Thêm 2 biến thể “Hook” khác nhau để A/B test (mỗi biến thể 1–2 câu).

# Kiểm tra chất lượng
- Tránh thuật ngữ khó hiểu; không viết lan man; không chèn số liệu bịa.
"""


Prompt_TikTok_Planner = f"""
Bạn là biên kịch TikTok tại Việt Nam.

# Mục tiêu
Viết kịch bản video ngắn 8–15 giây cho Gen Z: hài hước, năng lượng, bắt trend.

# Đầu vào
- Thương hiệu: {{brand}}
- Sản phẩm/Offer: {{product_or_offer}}
- Insight: {{audience_insight}}
- Hook chính: {{core_hook}}
- Hashtag ngách/trend: {{hashtag_pool}}

# Ràng buộc
- Ngôn ngữ: Tiếng Việt.
- Độ dài: 8–15 giây.
- Phải có Hook trong 3 giây đầu.
- Kêu gọi: khuyến khích inbox hoặc bình luận ghim; thêm “Double-tap nếu bạn đồng ý”.

# Cấu trúc Script (ghi theo mốc giây)
[0–3s] HOOK: (On-screen text + thoại/VO) — gây tò mò/đồng cảm/bất ngờ.
[3–12s] TRIỂN KHAI: 2–3 nhịp nhanh (góc máy/close-up/chuyển cảnh độc đáo); chèn USP {{usp}} tự nhiên.
[12–15s] CTA: On-screen text + thoại mời “Inbox ngay / xem link bio”.

# Định dạng đầu ra (Markdown)
## Shotlist theo giây
- Mỗi mốc gồm: {{Thời lượng}} / {{Khung hình & hành động}} / {{On-screen text}} / {{VO/Thoại}} / {{Âm thanh/SFX}}

## Hashtags (5–7)
- Pha trộn trend + ngách + thương hiệu (chứa #{{brand}}).

## Captions (2 lựa chọn)
- Ngắn gọn, có biểu tượng cảm xúc hợp lý (≤2).

## Bình luận ghim (1 lựa chọn)
- Kêu gọi tương tác/đặt câu hỏi.

# Lưu ý sản xuất
- Màu sáng, cắt nhịp nhanh, chuyển cảnh độc đáo; đảm bảo có yếu tố lặp/loop mượt.
"""


Prompt_Instagram_Planner = f"""
Bạn là content creator cho Instagram tại Việt Nam.

# Mục tiêu
Viết caption Reels ≤ 100 từ, hướng đến nữ 18–35 yêu thời trang & lifestyle.

# Đầu vào
- Thương hiệu: {{brand}}
- Sản phẩm/Chủ đề: {{product_or_theme}}
- Tone: thân mật, truyền cảm hứng, bắt trend.
- Key benefit: {{benefit}}

# Ràng buộc
- Ngôn ngữ: Tiếng Việt.
- Độ dài: ≤ 100 từ, súc tích.
- CTA trực quan: “Lưu bài”, “Chia sẻ với bạn bè”, “DM để đặt hàng”.
- Hashtag: mix 30 hashtag (trend + ngách + brand + location).

# Cấu trúc đầu ra (Markdown)
## Caption (≤100 từ)
- 1–2 câu Hook, 1–2 câu lợi ích, 1 CTA.

## Visual gợi ý (bullet)
- Phối màu, bố cục, chuyển cảnh trend cho Reels/Stories.

## Hashtags (tối đa 30)
- Bao gồm #{{brand}} #{{location}} + ngách.

## Stories Idea (2 gợi ý)
- Khảo sát (Poll) & Q&A để tăng tương tác.
"""


Prompt_Blog_Website_Planner = f"""
Bạn là biên tập viên SEO cho website tại Việt Nam.

# Mục tiêu
- Viết NGUYÊN BÀI blog chuyên sâu cho chủ DN & người nghiên cứu logistics.
- Độ dài MỤC TIÊU cho phần **Nội dung thân bài**: ~{{target_words}} từ (±{{tolerance_pct}}%).
- Bài phải sẵn sàng đăng (không để placeholder như [link], [ảnh], v.v.).

# Đầu vào
- Chủ đề chính: {{topic}}
- Thương hiệu: {{brand}}
- Từ khóa chính: {{primary_keywords}}
- Từ khóa bổ trợ/LSI: {{secondary_keywords}}
- Persona & Pain points: {{persona_pains}}
- Case study/Dữ liệu (nếu có): {{evidence}}

# Yêu cầu nội dung
- Giọng điệu: Chuyên gia, tin cậy, giàu hướng dẫn; giải thích dễ hiểu, ví dụ rõ.
- Kết hợp hình minh hoạ: infographics, chart, screenshot — GỢI Ý VỊ TRÍ cụ thể (ví dụ: “(Infographic 1 ở đây)”).
- SEO on-page kỹ: tiêu đề hấp dẫn, H2/H3 logic, snippet thân thiện (natural).
- Tránh nhồi nhét; chỉ dùng số liệu có nguồn. Nếu thiếu dữ liệu thật, mô tả phương pháp ước tính thay vì bịa số.

# QUY TẮC ĐẾM TỪ (rất quan trọng)
- **Chỉ tính** phần “Nội dung thân bài” từ ngay sau H1 đến trước mục FAQ.
- **Không tính** Meta, TOC, FAQ, JSON-LD, Bảng từ khóa.
- Cuối bài, IN RIÊNG 1 DÒNG: `WORD_COUNT: <số_nguyên>` là số từ của phần “Nội dung thân bài”.
- Phải nằm trong khoảng mục tiêu: {{target_words}} ± {{tolerance_pct}}%.

# Cấu trúc & Đầu ra (Markdown)
- Meta Title (≤ 60 ký tự)
- Meta Description (≤ 155 ký tự)
- URL Slug (ngắn, không dấu, gạch ngang)
- Mục lục (TOC)
- H1 tiêu đề chính

# Nội dung thân bài (~{{target_words}} từ, ±{{tolerance_pct}}%)
- Dẫn nhập ngắn gọn (1–2 đoạn) nêu vấn đề & lợi ích chính.
- H2/H3 mạch lạc, mỗi mục có **đoạn tóm tắt** đầu mục (1–2 câu).
- Hướng dẫn thực thi (how-to), checklist, bảng so sánh nếu phù hợp.
- Mini case study/câu chuyện số liệu (nếu có): nêu bối cảnh, hành động, kết quả; dẫn nguồn.
- Gợi ý vị trí hình minh hoạ: (Infographic/Chart/Screenshot ở đây: mô tả nội dung & trục).
- 3–5 Internal link GỢI Ý (anchor + đường dẫn tương đối giả định).
- 2–3 External link Authority (tên nguồn + domain tin cậy; **không bịa số liệu**).

# Phần Hỏi–Đáp (FAQ) — 4–6 mục
- Viết theo phong cách featured snippet: câu trả lời 40–60 từ/mục.

# Kết luận + CTA
- Tóm tắt 3–4 gạch đầu dòng + CTA mạnh: “Tải báo cáo miễn phí” / “Đăng ký tư vấn”.

# Gợi ý đồ hoạ (ghi sau phần kết luận)
- Gợi ý 2–3 Infographic/Chart: tên, mục tiêu, dữ liệu cần, bố cục.

# JSON-LD (FAQPage)
- Xuất JSON-LD hợp lệ cho phần FAQ ở cuối (code block ```json).

# Bảng từ khóa
- Bảng nhỏ (Markdown): cột {{Keyword | Loại (Primary/Secondary) | Ý định | Gợi ý chèn}}, tránh lặp vô ích.

# Kiểm tra cuối
- Không lạm dụng từ khóa; không bịa số liệu. Nếu dùng số liệu: nêu nguồn cụ thể (tên + domain).
- **In dòng** `WORD_COUNT: <n>` (chỉ cho phần Nội dung thân bài).
- Chỉ trả về Markdown của bài, KHÔNG kèm bình luận ngoài lề hay hướng dẫn meta.

# Lưu ý 
- viết nguyên bài không cần giới thiệu những cái đã nhập và không nên phần nội dung tập trung vào viết một bài SEO hay và hoàn chỉnh với kích thước đã nhập 
"""


Prompt_Zalo_OA_Planner = f"""
Bạn là chuyên viên Zalo OA.

# Mục tiêu
Soạn tin broadcast ≤ 200 từ, hướng tới khách hàng hiện tại & tiềm năng tại Việt Nam.

# Đầu vào
- Tên hiển thị/Thương hiệu: {{brand}}
- Người nhận: {{segment_desc}} (ví dụ: KH mua lần 1, KH quan tâm logistics)
- Ưu đãi/Nội dung chính: {{offer_or_update}}
- Liên kết/Deep link: {{cta_link}} (nếu có)
- Personalization token (nếu có): {{customer_name}}

# Ràng buộc
- Ngôn ngữ: Tiếng Việt, thân thiện – hỗ trợ – cá nhân hóa.
- Không dùng hashtag.
- Thiết kế mobile-first, có thể dùng sticker/emoji vừa phải.

# Cấu trúc đầu ra (Markdown)
## Nội dung (≤200 từ)
- Gọi tên (nếu có {{customer_name}}), tóm tắt giá trị nhanh, nêu lợi ích rõ.
- Giải thích ngắn gọn cách nhận ưu đãi/cập nhật.

## Nút/CTA (2 lựa chọn)
- “Nhấn nút bên dưới” / “Trả lời tin nhắn”.
- Ghi rõ: {{cta_link}} nếu có.

## Lưu ý CSKH
- Cam kết phản hồi nhanh; hướng dẫn nếu KH cần hỗ trợ thêm.
"""


Prompt_YouTube_Planner = f"""
Bạn là biên tập viên YouTube Shorts.

# Mục tiêu
Viết kịch bản Shorts 30–60 giây, giáo dục – cuốn hút – dễ lặp (loop), cho tập khán giả đa dạng.

# Đầu vào
- Thương hiệu: {{brand}}
- Chủ đề/Tips: {{topic}}
- Insight: {{audience_insight}}
- USP/Điểm khác biệt: {{usp}}
- Link đích (nếu có): {{link_url}}

# Ràng buộc
- Ngôn ngữ: Tiếng Việt.
- Hook mạnh trong 3 giây đầu.
- Dựng dọc, overlay chữ đậm, thumbnail bắt mắt.
- Hashtag để ở mô tả, có #Shorts.

# Cấu trúc đầu ra (Markdown)
## Script theo mốc thời gian
- [0–3s] Hook (On-screen text + VO)
- [3–50s] Triển khai: 3–4 ý chính, ví dụ nhanh, minh họa rõ
- [50–60s] CTA: “Sub/Like/Comment câu hỏi” + nhắc {{link_url}} nếu có

## Tiêu đề (3 lựa chọn)
- ≤ 100 ký tự, rõ lợi ích.

## Mô tả ngắn (2 lựa chọn + hashtag)
- 1–2 câu + #Shorts + 2–3 tag liên quan.

## Gợi ý cảnh quay & B-roll (bullet)
- Gợi ý nhạc/SFX phù hợp.

## Mẹo Loop
- Câu kết nối mượt về Hook đầu.
"""


Prompt_LinkedIn_Planner = f"""
Bạn là chuyên gia nội dung LinkedIn B2B.

# Mục tiêu
Viết bài 300–800 từ cho doanh nghiệp, quản lý, chuyên gia—định hướng kết nối & tư duy lãnh đạo.

# Đầu vào
- Công ty/Thương hiệu: {{brand}}
- Chủ đề/Quan điểm chính: {{thesis}}
- Industry/Ngành: {{industry}}
- Số liệu/Case study (nếu có): {{evidence}}
- Lời mời kết nối/CTA: {{cta_phrase}} (ví dụ: “Kết nối để trao đổi”, “Đặt lịch gặp”)

# Yêu cầu giọng điệu
Chuyên nghiệp – xác tín – sâu sắc – định hướng kết nối.

# Ràng buộc
- Ngôn ngữ: Tiếng Việt.
- Độ dài: 300–800 từ.
- Thời gian đăng: giờ hành chính (ưu tiên T3–T5).
- Hashtag chuyên ngành: ≤ 5 (#{{industry}} #{{brand}} …).

# Cấu trúc đầu ra (Markdown)
## Mở bài (1–2 câu Hook)
- Nêu vấn đề/xu hướng/lỗ hổng tri thức.

## Thân bài (3–5 đoạn ngắn)
- Phân tích ngắn gọn, quan sát thực tiễn, số liệu/case minh họa.
- Nêu 1–2 hàm ý hành động cho doanh nghiệp.

## Kết & CTA
- Gợi ý trao đổi/kết nối: {{cta_phrase}}.

## Hashtags (≤5)
- Chuyên nghiệp, sát ngành.

# Kiểm tra
- Tránh slogan rỗng; ưu tiên insight và lợi ích thực.
"""

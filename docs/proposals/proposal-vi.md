# Master Design Vault — Đề xuất hệ thống "Second Brain" cho Ngân hàng

> **Người đề xuất**: Hai Trieu — Solutions Architect
> **Ngày**: 2026-05-05
> **Phiên bản**: 2.0 (chia làm 2 MVP)
> **Đối tượng**: Brain Owner & Ban lãnh đạo công nghệ

---

## 1. Tóm tắt điều hành (TL;DR)

Ngân hàng vận hành **hàng chục hệ thống lớn** (core banking, payment, lending, channels…). Tài liệu thiết kế rải rác ở Confluence, Word, email, đầu các kiến trúc sư senior. **Mỗi lần ship code lên prod, tài liệu lại lệch thêm một bước**.

**Đề xuất**: Xây dựng **Master Design Vault** — kho tài liệu master tập trung của bank, dùng như "bộ não thứ hai" cho mọi developer. Chia làm **2 MVP**:

| | **MVP 1 — Foundation** | **MVP 2 — End-state** |
|---|---|---|
| **Quy mô** | GitLab repo markdown + Kiro local | Arkon + AWS Bedrock + MCP + auto-ingest |
| **Mục tiêu chính** | Validate value, build culture viết doc | Tự động hoá, scale toàn bank |
| **Thời gian** | 4-6 tuần | +8-12 tuần sau MVP 1 |
| **Đầu tư** | ~$3K (chủ yếu nội bộ) | ~$9K (gồm cả Bedrock + customize) |
| **Rủi ro** | 🟢 Thấp — không hạ tầng mới | 🟡 Trung — cần deploy stack mới |
| **Phụ thuộc compliance** | Không (data ở Git nội bộ) | Bật Bedrock access (1-2 ngày) |

**Logic chia MVP**: MVP 1 chứng minh **giá trị nhân văn** (developer thực sự dùng, doc thực sự được duy trì) **trước khi** đầu tư vào tự động hoá. Nếu MVP 1 không tạo ra adoption → dừng, không tốn thêm. Nếu MVP 1 chạy tốt → MVP 2 là bước scale tự nhiên.

---

## 2. Vấn đề cần giải quyết

### 2.1 Knowledge fragmentation hiện tại

```
   Confluence ──┐                ┌── Email threads
                │                │
   Word docs ───┼─→ ❓ ←─────────┤
                │   Senior         │
   Jira ────────┤   architect     ├── Slack messages
                │   trong đầu     │
   GitLab MR ───┘                └── Tài liệu cá nhân

   → Không có single source of truth
   → Code ship → tài liệu KHÔNG update → drift tăng dần
```

### 2.2 Rủi ro cụ thể trong banking

- **Compliance**: Audit yêu cầu chứng minh "code A khớp với design B" — hiện tại phải gom tay
- **Senior nghỉ**: Kiến thức về core banking integration mất theo người
- **Incident response**: Khi prod sự cố, tìm spec kiến trúc mất 30+ phút
- **Decision drift**: 6 tháng sau không ai nhớ tại sao team chọn pattern X
- **Duplication**: Team A và B cùng giải bài toán mà không biết nhau

---

## 3. MVP 1 — Foundation (Tuần 1-6)

### 3.1 Triết lý

> **"Get the habit first, automate later."**
>
> Bài toán lớn nhất không phải kỹ thuật — mà là **văn hoá viết doc**. MVP 1 cố ý giữ stack đơn giản nhất có thể, để focus 100% vào việc xây thói quen: "code merge → cập nhật doc → commit → review."

### 3.2 Kiến trúc

```
┌──────────────────────────────────────────────────────────┐
│  Layer 1 — VAULT (GitLab repo, markdown thuần)           │
├──────────────────────────────────────────────────────────┤
│  master-design/                                           │
│  ├── _index.md                ← Mục lục (con người viết) │
│  ├── systems/                                             │
│  │   ├── core-banking/                                    │
│  │   │   ├── overview.md                                  │
│  │   │   ├── api-contracts.md                             │
│  │   │   ├── integrations.md                              │
│  │   │   └── decisions/   ← ADR cho mọi quyết định lớn   │
│  │   ├── payment-gateway/                                 │
│  │   └── ...                                              │
│  ├── cross-cutting/         ← auth, logging, security    │
│  └── CONTRIBUTING.md        ← Quy tắc viết doc           │
└──────────────────────────┬───────────────────────────────┘
                           │ git clone / git pull
                           ▼
┌──────────────────────────────────────────────────────────┐
│  Layer 2 — INTERACTION (Kiro IDE local của engineer)     │
├──────────────────────────────────────────────────────────┤
│  • Mỗi engineer clone vault song song với project repo   │
│  • Kiro được config trỏ vào vault qua steering files     │
│  • Hỏi tự nhiên:                                          │
│    "Hệ thống Payment gọi Core Banking thế nào?"          │
│    → Kiro đọc markdown trong vault, trả lời + cite file  │
│  • Khi viết spec mới: Kiro auto-reference doc cũ        │
└──────────────────────────────────────────────────────────┘
```

**Không có gì khác**. Không server, không AI pipeline, không MCP, không auto-ingest. Đơn giản đến mức tối đa.

### 3.3 Workflow vận hành

```
1. Tạo repo GitLab `master-design` ở namespace của bank
2. Brain Owner viết CONTRIBUTING.md + skeleton _index.md
3. Mỗi team đóng góp ban đầu:
   ├─ Mỗi system pilot → 1 folder, seed 3-5 file MD core
   └─ Mỗi quyết định kiến trúc mới → 1 file ADR trong decisions/
4. Engineer làm việc:
   ├─ Clone vault song song với code repo
   ├─ Kiro được trỏ vào vault qua steering
   └─ Hỏi Kiro bất cứ lúc nào — Kiro đọc trực tiếp filesystem
5. Khi ship code lên prod:
   ├─ Engineer (hoặc tech lead) viết MR update doc trong vault
   └─ Brain Owner review + approve MR
```

### 3.4 Trong scope / ngoài scope

| ✅ Trong scope MVP 1 | ❌ Ngoài scope MVP 1 (để MVP 2) |
|---|---|
| GitLab repo markdown | AI tự động generate doc từ code |
| Mục lục, ADR, system overview | MCP server cho team-wide query |
| Kiro local đọc filesystem | Auto-ingest từ Confluence |
| MR review thủ công | Conflict detection tự động |
| Pilot 1-2 system | Cover toàn bộ ~50 system |
| 5-10 engineer dùng thử | 200+ engineer onboard |

### 3.5 Chi phí MVP 1

| Hạng mục | Tính toán | $ |
|---|---|---|
| Brain Owner (Tech Lead, part-time) | $2,500/tháng × 25% × 6 tuần | ~$900 |
| 2 engineer seed docs (part-time) | $2,000/tháng × 20% × 6 tuần × 2 | ~$1,200 |
| Kiro license (5-10 user pilot) | Theo team | ~$300-600 |
| Hạ tầng | GitLab đã có | $0 |
| Buffer | | ~$200 |
| **Tổng** | | **~$3K** |

**Cần xin ngân sách mới**: chỉ phần Kiro license (~$300-600). Phần còn lại là **opportunity cost nội bộ**.

### 3.6 Success criteria MVP 1

Đo lường ở tuần thứ 6:

- ✅ **80% engineer pilot** đã commit ít nhất 1 MR vào vault
- ✅ **≥20 ADR** được viết cho các quyết định trong 6 tuần
- ✅ **≥80% câu hỏi** "tại sao quyết định X?" trả lời được trong <2 phút qua Kiro
- ✅ **≥1 lần** vault giúp resolve incident hoặc onboarding nhanh hơn rõ rệt (case study)
- ✅ Brain Owner xác nhận: "muốn tiếp tục mở rộng" — đây là gate quyết định MVP 2

**Nếu không đạt 3/5 tiêu chí**: dừng, không đầu tư MVP 2. Đã tiết kiệm được phần lớn budget so với big-bang.

---

## 4. MVP 2 — End-state (Tuần 7-18)

### 4.1 Triết lý

> **"Automate what humans already proved valuable."**
>
> MVP 2 chỉ start khi MVP 1 đã chứng minh giá trị. Lúc đó việc đầu tư vào hạ tầng tự động hoá là an toàn vì đã có data sử dụng thật.

### 4.2 Kiến trúc end-state

```
┌─────────────────────────────────────────────────────────────────┐
│  📥 LAYER 1 — NGUỒN DỮ LIỆU                                     │
│  GitLab · Jira · Confluence · API contracts · DB schemas · ADR  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ webhooks + post-deploy hooks
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  🧠 LAYER 2 — AI PIPELINE (Arkon trên AWS, in-VPC)              │
│  • Change Management Process trigger sau khi deploy prod        │
│  • Diff extractor                                               │
│  • PII/PCI redactor (defense-in-depth)                          │
│  • Claude trên AWS Bedrock — data không egress                  │
│  • MRP pipeline: MAP → REDUCE → PLAN → REFINE → VERIFY          │
│  • CloudTrail audit log mọi Bedrock invocation                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ tạo MR (KHÔNG auto-merge)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  📚 LAYER 3 — VAULT (kế thừa từ MVP 1)                          │
│  • GitLab repo markdown (giống MVP 1)                           │
│  • Thêm: AI-generated entries qua MR                            │
│  • Brain Owner duyệt MR — human-in-the-loop bắt buộc            │
│  • Conflict log khi AI phát hiện mâu thuẫn                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ git pull cho local · MCP cho query
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  💻 LAYER 4 — INTERACTION                                       │
│  • Kiro local (kế thừa từ MVP 1)                                │
│  • Arkon MCP cho Claude Desktop / Claude.ai (team-wide query)   │
│  • RBAC scoped — mỗi user thấy đúng phạm vi của họ              │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 Stack công nghệ

| Lớp | Công nghệ | Lý do |
|---|---|---|
| Base platform | **Arkon** (fork từ github.com/hai123321/arkon) | Đã có MRP pipeline, MCP, RBAC, draft workflow — tiết kiệm 80% effort build từ đầu |
| AI engine | **Claude (Sonnet/Haiku) trên AWS Bedrock** | Data ở lại trong VPC, compliance-ready |
| Vault | GitLab repo markdown (kế thừa MVP 1) + Arkon DB | Người vẫn xem vault qua Git, MCP query qua Arkon |
| Audit | AWS CloudTrail + CloudWatch + Git history | Triple audit trail |
| Confluence migration | `tools/confluence-migration/migrate.py` (one-time CLI đã build) | One-time bulk import từ Confluence cũ |
| Interaction | Kiro IDE (local) + Claude Desktop (MCP) | Cover cả developer + non-dev (BA, PM) |

### 4.4 Lộ trình MVP 2

```
Tuần 7-8     │ Foundation
             │ • Deploy Arkon trên AWS (docker-compose hoặc ECS)
             │ • Viết bedrock_provider.py cho Arkon
             │ • Bật Bedrock model access (1-2 ngày)
             │
Tuần 9-10    │ One-time migration
             │ • Chạy tools/confluence-migration cho 2-3 space Confluence
             │ • Brain Owner review compilation plan
             │ • Verify wiki output trên Arkon portal
             │
Tuần 11-13   │ Auto-ingestion
             │ • GitLab CI post-deploy webhook → Arkon ingest endpoint
             │ • AI tạo MR vào vault repo (KHÔNG auto-merge)
             │ • Brain Owner duyệt MR đầu tiên — tinh chỉnh prompt
             │
Tuần 14-16   │ Scale + MCP rollout
             │ • Mở rộng auto-ingest cho 5 system
             │ • Phát hành MCP token cho 30-50 engineer
             │ • Dashboard adoption + conflict tracking
             │
Tuần 17-18   │ Hardening + handoff
             │ • SOP cho Brain Owner
             │ • Runbook cho operation team
             │ • Quyết định roll-out toàn bank
```

### 4.5 Chi phí MVP 2

| Hạng mục | Tính toán | $ |
|---|---|---|
| Senior engineer | $2,500/tháng × 3 tháng | ~$7,500 |
| AI API (Bedrock, 3 tháng) | ~$100/tháng × 3 | ~$300 |
| AWS infra (Lambda/ECS, RDS, OpenSearch) | ~$150/tháng × 3 | ~$450 |
| Buffer | | ~$750 |
| **Tổng MVP 2** | | **~$9K** |

**Cộng dồn cả MVP 1 + 2**: ~$12K trong 4-5 tháng.

### 4.6 Success criteria MVP 2

- ✅ **Code merge → doc auto-update qua MR ≤ 24h**
- ✅ **≥80% AI-generated MR** được Brain Owner approve không cần edit lớn
- ✅ **≥30 engineer** dùng Arkon MCP/Kiro hàng tuần
- ✅ **2-3 Confluence space** migrate xong, đối chiếu content khớp
- ✅ Audit trail CloudTrail + Git history pass compliance review

---

## 5. ROI cộng dồn 3 năm

Giả định: 50 dev, $12/h, 15 hires/năm, 4 audit/năm, 10 incidents/năm.

| Hạng mục | $/năm |
|---|---|
| Onboarding nhanh hơn (15 hires × 23 ngày × 8h × $12) | $33,120 |
| Search/research giảm (30 dev × 4h × 50 tuần × $12) | $72,000 |
| Audit prep nhanh hơn | $13,440 |
| Incident MTTR -15% | $7,500 |
| Senior departure insurance | $10,000 |
| **Tổng (conservative)** | **~$136K/năm** |

**3-year cumulative**:

| Năm | Cost | Savings | Net | Cumulative |
|---|---|---|---|---|
| Năm 1 (MVP 1 + MVP 2 + ramp 50%) | $12K + $14K ops = $26K | $68K | +$42K | +$42K |
| Năm 2 (steady state) | $14K | $136K | +$122K | +$164K |
| Năm 3 (maturity) | $14K | $180K | +$166K | +$330K |
| **Tổng 3 năm** | **$54K** | **$384K** | | **Net +$330K (~6×)** |

---

## 6. Quản trị rủi ro

| Rủi ro | Mức độ | Biện pháp |
|---|---|---|
| MVP 1 không tạo được adoption | 🟡 Trung | Pilot 1 squad, gate chặt ở tuần 6, sẵn sàng dừng |
| AI hallucinate | 🔴 Cao | Mandatory citation, MR review, audit log |
| Lộ data qua AI | 🟢 Thấp | Bedrock in-VPC, không egress, Anthropic không train |
| Vault thành nghĩa địa doc | 🟡 Trung | MVP 1 build habit trước, MVP 2 thêm tự động |
| Cost vượt budget | 🟢 Thấp | Sonnet vs Haiku, batch ingest, alert ngưỡng |

---

## 7. Đề xuất quyết định

### Xin phê duyệt ngay (MVP 1)

1. **Phase 1 — MVP 1 Foundation** (6 tuần, ~$3K opportunity cost, chỉ ~$600 cash mới cho Kiro license)
2. **Brain Owner**: chỉ định 1 Tech Lead làm Brain Owner, allocate 25% thời gian
3. **Pilot system**: chọn 1-2 system có doc tệ nhất, blast radius thấp
4. **Success gate ở tuần 6**: review theo 5 tiêu chí, quyết định có chạy MVP 2 hay không

### Phê duyệt có điều kiện (MVP 2)

5. Approval phụ thuộc kết quả MVP 1. Nếu pass gate → kick off MVP 2 với:
   - Bật AWS Bedrock model access (1-2 ngày)
   - Allocate 1 senior × 3 tháng
   - Budget ~$9K (gồm Bedrock + AWS infra + buffer)

### Câu hỏi mở

1. **Brain Owner candidate**: ai sẽ đảm nhiệm vai trò Brain Owner trong MVP 1?
2. **Pilot system**: Ban lãnh đạo muốn chọn system nào?
3. **AWS region**: dùng `ap-southeast-1` (Singapore) hay region nào khác cho Bedrock?
4. **Confluence scope**: MVP 2 migrate space nào trước?

---

*Đề xuất này được xây dựng trên pattern Karpathy "LLM Wiki" và base codebase Arkon (open source), điều chỉnh cho ngữ cảnh banking với compliance, audit và human-in-the-loop là ưu tiên cao nhất.*

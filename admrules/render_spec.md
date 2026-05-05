# admrules render spec

Status: draft implementation seed.

This file freezes the Python-side rendering rules used by `admrules.converter`
before the Rust compiler parity gate exists.

- Repository layout:
  `{기관경로...}/{행정규칙종류}/{행정규칙명}/본문.md`.
- `기관경로` is based on normalized `상위부처명`, `소관부처명`, and
  `담당부서기관명`, then corrected with legal parent relationships from
  `정부조직법` and agency-specific installation laws. If the resolved agency has
  no distinct legal parent and the normalized top/ministry are identical, append
  `_본부` before the rule-type component.
- Ministry resolution also applies the current rename map and source-data fixes:
  date-like `소관부처명` values fall back to `상위부처명`; a compound
  `상위부처명` such as `기후에너지환경부 국립환경과학원` is split when
  `담당부서기관명` confirms the attached agency; and split historical ministries
  are only moved to a current top-level agency when the source ministry is not a
  current root, or when a verified current function-transfer pair exists. For
  example, `국토해양부` with `해양수산부(해양영토과)` moves to
  `해양수산부`, and `산업통상부` with
  `기후에너지환경부(전력산업정책과)` moves to `기후에너지환경부`.
  River-management rules with `기후에너지환경부(하천계획과)` are also kept
  under `기후에너지환경부/_본부` even when the source `소관부처명` is
  `국토교통부`.
  A current root is not replaced merely because another agency appears in
  `담당부서기관명`.
- If the API already provides a current top-level agency in `상위부처명` but
  `소관부처명` is a historical root-level ministry name inherited by that
  current agency, the historical name is folded into the current headquarters
  path instead of being treated as a sub-agency. For example,
  `농림축산식품부/농림수산식품부/...` becomes
  `농림축산식품부/_본부/...`, while fishery-side
  `해양수산부/농림수산식품부/...` becomes `해양수산부/_본부/...`.
- Legal parent chains are represented in the path when the law defines them:
  `국방부/병무청/...`, `재정경제부/국세청/...`,
  `재정경제부/관세청/...`, `농림축산식품부/산림청/...`,
  `국무총리/법제처/...`, `대통령/국가교육위원회/...`,
  `과학기술정보통신부/국립전파연구원/...`,
  `과학기술정보통신부/중앙전파관리소/...`, and
  `대통령/방송미디어통신위원회/방송미디어통신사무소/...`.
- `국립전파연구원` and `중앙전파관리소` are separate current
  `과학기술정보통신부` affiliated agencies. Current
  `방송미디어통신위원회` is a presidential commission, and its current
  affiliated agency is `방송미디어통신사무소`.
- A stale `방송통신위원회` source ministry is not moved to
  `대통령/방송미디어통신위원회` when `담당부서기관명` explicitly points to
  `과학기술정보통신부(...)`.
- Special or independent bodies are not merged into a ministry unless a law
  gives a concrete parent. `10·29이태원참사진상규명과재발방지를위한특별조사위원회`,
  `세월호 선체조사위원회`, `국가인권위원회`, `고위공직자범죄수사처`,
  and `중앙선거관리위원회` remain separate roots. A law's administrative
  owner or contact ministry is not treated as the committee's parent unless the
  installation article places the committee under that ministry.
- `정부산하기관및위원회` is only replaced for specifically verified bodies:
  `수도권매립지관리공사` maps to `기후에너지환경부/수도권매립지관리공사`,
  and `평생교육진흥원` is normalized to `국가평생교육진흥원` under
  `교육부`.
- The current rename map includes same-agency organization changes such as
  `국립환경인력개발원` to `국립환경인재개발원`, and current central-agency
  names such as `행정자치부` to `행정안전부` and `기획재정부` to
  `재정경제부`.
- Path components are NFC-normalized, slash-like separators are replaced with
  spaces, repeated whitespace is collapsed, and each stem is capped at 180 UTF-8
  bytes.
- Collisions on identical `(기관경로, 행정규칙종류, 행정규칙명)` paths are
  resolved by suffixing the rule-name directory with `_{발령번호}`; if
  `발령번호` is empty, use `행정규칙일련번호`.
- `발령일자` is the future Git author date source. Dates before 1970-01-01 are
  clamped to 1970-01-01 in frontmatter with `발령일자보정: true` and the raw
  API text preserved in `발령일자원문`.
- `본문출처` is one of `api-text`, `parsed-from-hwp`, `parsing-failed`.
- Binary attachments are never written to the Git tree. Attachment frontmatter
  is written under `첨부파일` as link metadata only, with `파일링크` and/or
  `PDF링크` when upstream provides 별표/서식 download links.
- `core/git_engine.py` SHA pin: pending. The shared core engine is owned by the
  ordinance first-consumer work and is intentionally not pinned in this seed.

## Legal sources

- `정부조직법`: 대통령·국무총리 소속 기관, 부처별 외청 관계, `국세청`·`관세청`·`조달청`, `병무청`, `산림청` 등. https://www.law.go.kr/법령/정부조직법
- `방송미디어통신위원회의 설치 및 운영에 관한 법률` 제3조: 대통령 소속. https://www.law.go.kr/법령/방송미디어통신위원회의설치및운영에관한법률
- `국가교육위원회 설치 및 운영에 관한 법률` 제2조: 대통령 소속 및 독립 수행. https://www.law.go.kr/법령/국가교육위원회설치및운영에관한법률
- `방송미디어통신위원회의 설치 및 운영에 관한 법률` 제3조 및 `방송미디어통신위원회와 그 소속기관 직제` 제2조: 대통령 소속 위원회와 `방송미디어통신사무소` 근거.
- `과학기술정보통신부와 그 소속기관 직제` 제2조·제25조·제30조·제31조: `국립전파연구원`, `중앙전파관리소`, `전파시험인증센터`, `위성전파감시센터` 근거.
- `독점규제 및 공정거래에 관한 법률` 제54조, `부패방지 및 국민권익위원회의 설치와 운영에 관한 법률` 제11조, `금융위원회의 설치 등에 관한 법률` 제3조, `개인정보 보호법` 제7조, `원자력안전위원회의 설치 및 운영에 관한 법률` 제3조: 국무총리 소속 위원회.
- `우주항공청의 설치 및 운영에 관한 특별법` 제6조: 과학기술정보통신부장관 소속. https://www.law.go.kr/법령/우주항공청의설치및운영에관한특별법
- `신행정수도 후속대책을 위한 연기ㆍ공주지역 행정중심복합도시 건설을 위한 특별법` 제38조 및 `새만금사업 추진 및 지원에 관한 특별법` 제34조: 국토교통부장관 소속 청.
- `검찰청법` 제2조·제8조·제11조, `농림축산식품부와 그 소속기관 직제`, `민주평화통일자문회의법` 제6조·제9조: `대검찰청`, `국립농산물품질관리원`, `민주평화통일자문회의사무처` 위치 보정 근거.
- `수도권매립지관리공사의 설립 및 운영 등에 관한 법률` 제5조·제7조, `평생교육법` 제19조: 공공기관 위치 보정 근거.
- `국가인권위원회법` 제3조 및 `고위공직자범죄수사처 설치 및 운영에 관한 법률` 제3조: 특정 상위기관에 편입하지 않는 독립기관 근거.
- `10ㆍ29이태원참사 피해자 권리보장과 진상규명 및 재발방지를 위한 특별법` 제6조·제7조 및 `세월호 선체조사위원회의 설치 및 운영에 관한 특별법` 제3조·제4조·제9조: 특정 부처에 편입하지 않는 한시 조사위원회 근거.

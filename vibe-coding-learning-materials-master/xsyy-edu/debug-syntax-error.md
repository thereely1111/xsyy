# Debug Session: syntax-error

Status: VERIFIED

## Symptom
`python -m uvicorn app:app --reload` fails while importing `database.models`.

## Hypotheses
1. `database/models.py` contains invalid text at the reported line.
2. The `ip_address` column declaration itself is valid once the stray text is removed.
3. No additional syntax error remains after the minimal correction.

## Pre-fix Evidence
`python -m py_compile database/models.py` reproduces:

```text
File "database\\models.py", line 28
  方程与不等式 / 七下 / 二元一次方程组 / 二元一次方程组应用题    ip_address = Column(String(64), nullable=True)  # 注册时记录的客户端 IP
SyntaxError: invalid syntax
```

The failing token is the un-commented Chinese course-path text before `ip_address`.

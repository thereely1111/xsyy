ALTER TABLE teachings
ADD COLUMN has_pic TINYINT(1) NOT NULL DEFAULT 0
AFTER is_math_problem;


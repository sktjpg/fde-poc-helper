"""Example tool: deterministic, typed, independently testable."""

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.tools.base import Tool
from app.domain.errors import ToolError


class CalculatorArgs(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation: Literal["add", "subtract", "multiply", "divide"]
    a: float = Field(allow_inf_nan=False)
    b: float = Field(allow_inf_nan=False)


class CalculatorResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    result: float


async def calculate(args: CalculatorArgs) -> CalculatorResult:
    match args.operation:
        case "add":
            value = args.a + args.b
        case "subtract":
            value = args.a - args.b
        case "multiply":
            value = args.a * args.b
        case "divide":
            if args.b == 0:
                raise ToolError("Cannot divide by zero")
            value = args.a / args.b
    if not math.isfinite(value):
        raise ToolError("Result is too large to represent")
    return CalculatorResult(result=value)


calculator = Tool(
    name="calculator",
    description="Arithmetic on two numbers. Use it instead of computing mentally.",
    args_model=CalculatorArgs,
    handler=calculate,
)

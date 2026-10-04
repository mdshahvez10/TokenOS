from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from tokenos.application.execution import InstrumentedCall, ModelResult


class BaselineState(TypedDict):
    run_id: UUID
    reservation_id: UUID
    prompt: str
    max_output_tokens: int


class BaselineOutput(TypedDict):
    result: ModelResult


class GraphState(BaselineState, BaselineOutput):
    pass


def build_baseline(
    call: InstrumentedCall,
) -> CompiledStateGraph[GraphState, None, BaselineState, BaselineOutput]:
    async def invoke(state: BaselineState) -> BaselineOutput:
        result = await call.execute(**state)
        return {"result": result}

    graph = StateGraph(GraphState, input_schema=BaselineState, output_schema=BaselineOutput)
    graph.add_node("instrumented_model", invoke)
    graph.add_edge(START, "instrumented_model")
    graph.add_edge("instrumented_model", END)
    return graph.compile()

from typing import Any, List, Mapping, Optional, Union, Dict
from pydantic import BaseModel, ConfigDict
from langchain_core.language_models.llms import LLM
from langchain_core.callbacks import CallbackManagerForLLMRun
from ibm_watson_machine_learning.foundation_models import Model
from langchain_community.llms.utils import enforce_stop_tokens
from langchain_core.outputs import LLMResult, Generation

# Updated LangChainInterface model with modern LangChain structure
class LangChainInterface(LLM):

    credentials: Optional[Dict] = None
    model: Optional[str] = None
    params: Optional[Dict] = None
    project_id: Optional[str] = None

    model_config = ConfigDict(
        extra='forbid'  # Updated from pydantic v1 to v2 syntax
    )

    @property
    def _identifying_params(self) -> Mapping[str, Any]:
        """Get the identifying parameters."""
        _params = self.params or {}
        return {
            **{"model": self.model},
            **{"params": _params},
        }
    
    @property
    def _llm_type(self) -> str:
        """Return type of llm."""
        return "IBM WATSONX"

    def _generate(
        self,
        prompts: List[str],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> LLMResult:

        generations = []
        total_prompt_tokens = 0
        total_completion_tokens = 0

        model = Model(
            model_id=self.model,
            params=self.params or {},
            credentials=self.credentials,
            project_id=self.project_id
        )

        for prompt in prompts:
            response = model.generate(prompt)

            result = response["results"][0]
            text = result["generated_text"]

            if stop is not None:
                text = enforce_stop_tokens(text, stop)

            generations.append([Generation(text=text)])

            total_prompt_tokens += result.get("input_token_count", 0)
            total_completion_tokens += result.get("generated_token_count", 0)

        token_usage = {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
        }

        return LLMResult(
            generations=generations,
            llm_output={"token_usage": token_usage}
        )

    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> str:
        params = self.params or {}

        model = Model(
            model_id=self.model,
            params=params,
            credentials=self.credentials,
            project_id=self.project_id
        )

        response = model.generate(prompt)

        text = response["results"][0]["generated_text"]

        if stop is not None:
            text = enforce_stop_tokens(text, stop)

        token_usage = {
            "prompt_tokens": response["results"][0].get("input_token_count", 0),
            "completion_tokens": response["results"][0].get("generated_token_count", 0),
            "total_tokens": response["results"][0].get("total_token_count", 0),
        }

        if run_manager:
            run_manager.on_llm_end(
                LLMResult(
                    generations=[[Generation(text=text)]],
                    llm_output={"token_usage": token_usage}
                )
            )

        return text

    def invoke(self, input: str, **kwargs) -> str:
        """Modern invoke method that calls _call internally"""
        return self._call(input, **kwargs)

    async def ainvoke(self, input: str, **kwargs) -> str:
        """Async invoke method"""
        # For now, just call the sync version
        # You can implement true async later if needed
        return self.invoke(input, **kwargs)

    def batch(self, inputs: List[str], **kwargs) -> List[str]:
        """Batch processing method"""
        return [self.invoke(input, **kwargs) for input in inputs]

    async def abatch(self, inputs: List[str], **kwargs) -> List[str]:
        """Async batch processing method"""
        return [await self.ainvoke(input, **kwargs) for input in inputs]

    def stream(self, input: str, **kwargs):
        """Stream method - yields the complete response for now"""
        # IBM Watson doesn't support streaming by default
        # So we'll yield the complete response
        result = self.invoke(input, **kwargs)
        yield result

    async def astream(self, input: str, **kwargs):
        """Async stream method"""
        result = await self.ainvoke(input, **kwargs)
        yield result
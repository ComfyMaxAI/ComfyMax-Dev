from __future__ import annotations

import base64
from threading import RLock

_MODEL_LOCK = RLock()
from dataclasses import dataclass
from typing import Any

import requests


class LMStudioError(RuntimeError):
    """Readable error raised for LM Studio communication failures."""


@dataclass(frozen=True)
class LoadedInstance:
    model: str
    instance_id: str


class ModelLoadConfirmationRequired(LMStudioError):
    def __init__(self, instances: list[LoadedInstance]) -> None:
        self.instances = instances
        super().__init__("Confirm unloading the currently loaded LM Studio instances first.")


@dataclass(frozen=True)
class GeneratedPrompt:
    text: str
    model: str
    instance_id: str | None


class LMStudioClient:
    def __init__(self, base_url: str, timeout: int = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            detail = getattr(exc.response, "text", "") if exc.response is not None else ""
            raise LMStudioError(
                f"LM Studio is unreachable or returned an error at {path}. {detail or exc}"
            ) from exc

    def list_models(self) -> list[str]:
        data = self._request("GET", "/v1/models").json()
        return [item["id"] for item in data.get("data", []) if item.get("id")]

    def loaded_instances(self) -> list[LoadedInstance]:
        """Fail closed if the native API cannot establish the loaded state."""
        data = self._request("GET", "/api/v1/models").json()
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise LMStudioError("Cannot verify LM Studio loaded models: invalid response.")
        result = []
        for item in data["models"]:
            if not isinstance(item, dict) or not isinstance(item.get("loaded_instances"), list):
                raise LMStudioError("Cannot verify LM Studio loaded instances.")
            for instance in item["loaded_instances"]:
                if (not isinstance(instance, dict) or not instance.get("id")
                        or not item.get("key")):
                    raise LMStudioError("LM Studio returned an unidentified loaded instance.")
                result.append(LoadedInstance(item["key"], instance["id"]))
        return result

    def _find_instance_id(self, model: str) -> str | None:
        for instance in self.loaded_instances():
            if model in (instance.model, instance.instance_id):
                return instance.instance_id
        return None

    def load_model(
        self, model: str, *, approved_instances: list[LoadedInstance] | None = None,
    ) -> str:
        # Serialize loads across client objects and Streamlit sessions in this process.
        with _MODEL_LOCK:
            instances = self.loaded_instances()
            if len(instances) == 1 and model in (instances[0].model, instances[0].instance_id):
                return instances[0].instance_id
            if instances:
                if approved_instances is None or not set(instances).issubset(set(approved_instances)):
                    raise ModelLoadConfirmationRequired(instances)
                for instance in instances:
                    self.unload_model(instance.instance_id)
                # Never assume that a successful unload response means memory is clear.
                remaining = self.loaded_instances()
                if remaining:
                    raise ModelLoadConfirmationRequired(remaining)
            data = self._request(
                "POST", "/api/v1/models/load", json={"model": model},
            ).json()
            instance_id = data.get("instance_id") or data.get("model_instance_id")
            if not instance_id:
                raise LMStudioError("LM Studio did not return an instance_id after loading.")
            return instance_id

    def generate_prompt(
        self,
        user_request: str,
        model: str,
        system_prompt: str,
        temperature: float = 0.7,
        images: list[tuple[bytes, str | None]] | None = None,
    ) -> GeneratedPrompt:
        user_content: str | list[dict[str, Any]]

        if images:
            user_content = [{"type": "text", "text": user_request}]
            for index, (image_data, image_mime_type) in enumerate(images, start=1):
                mime_type = image_mime_type or "image/png"
                encoded_image = base64.b64encode(image_data).decode("ascii")
                user_content.append({"type": "text", "text": f"<Picture {index}>"})
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"},
                })
        else:
            user_content = user_request

        instance_id = self.load_model(model)
        payload = {
            "model": instance_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
        }

        data = self._request(
            "POST",
            "/v1/chat/completions",
            json=payload,
        ).json()

        try:
            text = data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LMStudioError("LM Studio did not return a usable prompt.") from exc

        return GeneratedPrompt(
            text=text,
            model=data.get("model", model),
            instance_id=instance_id,
        )

    def unload_model(self, instance_id: str | None) -> None:
        if not instance_id:
            raise LMStudioError(
                "No LM Studio instance_id was found. Unload the model manually "
                "or check the LM Studio REST API."
            )

        self._request(
            "POST",
            "/api/v1/models/unload",
            json={"instance_id": instance_id},
        )

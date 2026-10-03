"""FoodLink Predict - AI food waste prediction, prevention and early redistribution.

Built ON TOP OF the Hackathon Starter Toolkit V4. Nothing here modifies the
toolkit core: the project reuses app.core.config, app.core.errors,
app.ai.llm_service, app.agents (node/LangGraph pattern), app.ml (optional
sklearn) and app.maps (haversine).

Division of responsibility
--------------------------
FoodLink Predict : the EARLY INTELLIGENCE PRODUCER. Forecasts demand, scores
                   waste risk, ranks actions, explains them, and publishes a
                   *forecast* surplus listing.
FoodLink          : the REDISTRIBUTION EXECUTOR. Its six agents (detect, match,
                   negotiate, hand off, deliver, verify) are never touched;
                   Predict only reaches them through the thin adapter in
                   app/projects/foodlink_predict/adapters/.
"""

__version__ = "1.0.0"
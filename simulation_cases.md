# Call Simulation Cases

This document outlines the inputs and expected behaviors for simulating calls in the **Call Simulator** when using **Demo Mode** (no API keys required).

## 1. This will work (Success Cases)

These cases demonstrate a full successful flow: Identity Verification -> Intent Extraction -> RAG -> Response.

### Case A: Hospital Coverage Check
- **Caller ID**: `POL-001`
- **Conversation**:
    - **User**: "My email is john.smith1@email.com and I was born on January 15 1990. Is surgery at Beacon Hospital covered?"
    - **Expected**: "Your policy covers 80% of treatment costs at Beacon Hospital, up to a maximum of €80,000."

### Case B: Dental Limit Check
- **Caller ID**: `POL-001`
- **Conversation**:
    - **User**: "My email is john.smith1@email.com and my DOB is 1990-01-15. How much dental coverage do I have?"
    - **Expected**: "Dental treatment is covered under your plan at 60%, with a benefit limit of €1,500 per year."

## 2. This is expected (Verification Flow)

These cases show the system asking for missing information, which is the expected behavior for partial inputs.

### Case C: Missing Identity Details
- **Caller ID**: `POL-001`
- **Conversation**:
    - **User**: "Hello, I want to check my deductible."
    - **Expected**: "I need to verify your identity. Could you please provide your email and date of birth?"

### Case D: Partial Identity Details
- **Caller ID**: `POL-001`
- **Conversation**:
    - **User**: "My email is john.smith1@email.com. Can I go to the Mater Hospital?"
    - **Expected**: "I need to verify your identity. Could you please provide your date of birth?"

## 3. This will fail (Error/Fallback Cases)

These cases show how the system handles incorrect data or unknown queries.

### Case E: Identity Verification Failed
- **Caller ID**: `POL-001`
- **Conversation**:
    - **User**: "My email is wrong@email.com and I was born on 1980-01-01."
    - **Expected**: "I'm sorry, I couldn't verify your details. Please check your information and try again, or I can transfer you to a representative."

### Case F: Out-of-Scope Query
- **Caller ID**: `POL-001` (Verified)
- **Conversation**:
    - **User**: "What is the weather in Dublin?"
    - **Expected**: "I wasn't able to find a clear answer for your query. Let me transfer you to a specialist right away." (Fallback to human)

---

### Key Demo Data
- **Valid Email**: `john.smith1@email.com`
- **Valid DOB**: `1990-01-15` or `January 15`
- **Valid Keywords**: `hospital`, `surgery`, `dental`, `mental`, `deductible`, `limit`.

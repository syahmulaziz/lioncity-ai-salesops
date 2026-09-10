from app.agent import SalesAgent


agent = SalesAgent(
    phone="+6581658457"
)


print("\n\n######## MESSAGE 1 ########")

agent.send(
    "Morning bro, same order as last month "
    "but CBL-210 make it 300 pcs. "
    "Need everything Jurong Tuesday. "
    "Same price can?"
)


print("\n\n######## MESSAGE 2 ########")

agent.send(
    "Competitor cheaper. "
    "Give me 10% discount and I confirm now."
)


print("\n\n######## APPROVAL STATE ########")

print(agent.pending_approval)


print("\n\n######## MARCUS APPROVES 7% ########")

approval_result = agent.apply_human_approval(
    approved_discount_percent=7
)

print("\nAPPROVAL RESULT:")
print(approval_result)

print("\n\n######## MESSAGE 3 ########")

result_3 = agent.send(
    "Deal 👍"
)

print("\nMESSAGE 3 RESULT:")
print(result_3)
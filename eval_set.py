"""Labelled floor messages used to measure extraction accuracy.

Each item: the message a supervisor might send, and the fields we expect the AI to extract.
"""

EVAL_SET = [
    {"text": "Truck 4 mein order 551 ke teen sau carton load ho gaye hain.", "event_type": "loaded", "order_id": 551, "cartons": 300},
    {"text": "Order 552 ka truck TRK-1 port ke liye nikal gaya.", "event_type": "dispatched", "order_id": 552, "cartons": None},
    {"text": "Order 555 ka kapra abhi dyeing mein hai, do din late hoga.", "event_type": "delayed", "order_id": 555, "cartons": None},
    {"text": "20 cartons of order 554 got wet in the rain at the loading bay.", "event_type": "damaged", "order_id": 554, "cartons": 20},
    {"text": "آرڈر 553 کے ڈیڑھ سو کارٹن ٹرک 3 میں لوڈ ہو گئے ہیں۔", "event_type": "loaded", "order_id": 553, "cartons": 150},
    {"text": "551 wale order ka truck nikal gaya hai.", "event_type": "dispatched", "order_id": 551, "cartons": None},
    {"text": "Loaded 120 cartons for order 555 on truck 6.", "event_type": "loaded", "order_id": 555, "cartons": 120},
    {"text": "Order 554 ki packing mein masla hai, kal tak delay hoga.", "event_type": "delayed", "order_id": 554, "cartons": None},
    {"text": "Order 552 ke 15 carton phat gaye, maal kharab ho gaya.", "event_type": "damaged", "order_id": 552, "cartons": 15},
    {"text": "TRK-2 mein 551 ke do sau carton aur chadh gaye.", "event_type": "loaded", "order_id": 551, "cartons": 200},
    {"text": "آرڈر 554 کا ٹرک فیکٹری سے روانہ ہو گیا ہے۔", "event_type": "dispatched", "order_id": 554, "cartons": None},
    {"text": "Order 553 is delayed because the buyer changed the labels.", "event_type": "delayed", "order_id": 553, "cartons": None},
    {"text": "Pachaas carton order 554 ke truck 5 pe load kar diye.", "event_type": "loaded", "order_id": 554, "cartons": 50},
    {"text": "Truck 3 left with order 553.", "event_type": "dispatched", "order_id": 553, "cartons": None},
    {"text": "آرڈر 555 کے دس کارٹن گیلے ہو گئے ہیں۔", "event_type": "damaged", "order_id": 555, "cartons": 10},
    {"text": "Order 552 ke 100 carton load ho gaye, baqi kal.", "event_type": "loaded", "order_id": 552, "cartons": 100},
    {"text": "551 ka maal abhi stitching se nahi aaya, shipment late hogi.", "event_type": "delayed", "order_id": 551, "cartons": None},
    {"text": "Forklift kharab ho gayi hai loading bay pe.", "event_type": "other", "order_id": None, "cartons": None},
    {"text": "Do sau pachaas carton order 553 ke load ho chuke hain truck 7 mein.", "event_type": "loaded", "order_id": 553, "cartons": 250},
    {"text": "Order 555 dispatched on truck TRK-8 at 4 pm.", "event_type": "dispatched", "order_id": 555, "cartons": None},
]

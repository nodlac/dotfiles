from apps.iterable import client as iterable_client
import pandas as pd

test_list = [
    {
        'email': 'caldonpreece@gmail.com', 
        'code':'6P7IC3QTPZBTI2S5', 
        'amount': '10', 
        'pin': 5753
    }
]

recipients = pd.read_csv('link_to_csv')

card_amount = 1000


recipients_list_dict = recipients.to_dict(orient='records')

def send_gift_cards(cards): 
    sent = 0
    for event in cards:
        # create a card 
        data = {
            'from_name': "VidAngel",
            'gift_card_amount': event['amount'],
            'gift_card_code': event['code'],
            'gift_card_pin': event['pin'],
        }
        iterable_client.track_event(
            email = event['email'],
            event_name = 'emailGiftCardCode',
            data_fields = data
        )
        sent += 1
send_gift_cards(recipients_list_dict)

# Going live with the brain, and going back

This is the plain-English guide to the brain's three trading stages and how to undo any of them. Everything here is done on the Brain page (Trading stage card) unless it says otherwise.

## What the three stages mean

- **Practice (shadow).** The brain's ideas are recorded and scored next to version 1. Nothing is bought.
- **Your OK needed.** Each brain idea waits on the Brain page. Nothing is bought until you press Approve.
- **Automatic.** The brain's ideas are bought without asking, through version 1's normal safety checks. You can switch back to practice at any time.

The brain always starts in Practice. Nothing in the app changes the stage by itself; only you can, on the Brain page.

## How to move on

1. Open the Brain page and find **Trading stage**.
2. The card shows "N of 30 brain ideas have finished". You can leave Practice only once 30 have finished, so there is evidence to look at. Until then the other stages are greyed out.
3. Pick **Your OK needed**, write a reason, press **Change stage**.
4. **Automatic** can only be chosen from "Your OK needed". There is no extra test beyond the 30 finished ideas: moving to Automatic is your own call, made on your own judgement of how the practice and approval stages have gone.
5. A reason is always required. Every change is recorded with who made it, when, and why; the list is shown under the card.

### How approving works

- In "Your OK needed", each idea appears under **Waiting for your OK**.
- Approve checks again that the brain still likes the idea, that you do not already hold the stock through the brain, and that the safety rules allow the purchase. Only then is it bought.
- An idea stays open until the next trading day's market closes. If you approve while the market is closed, nothing is ordered at that moment. It shows as "Approved — will be placed when the market opens", and the checks run once more at the open before anything is bought. An order is never sent after the market has closed.
- An idea you do not approve in time expires. Rejecting an idea needs a short reason.
- While the stage is Practice, Approve is not shown at all.

## How to go back (rollback)

There is one switch for this.

1. Brain page, **Trading stage**, choose **Practice (shadow)**, write a reason, press **Change stage**. (For developers: `PUT /api/v1/brain/stage` with `{"stage":"shadow","reason":"..."}`.)
2. It takes effect at once. Going back to Practice is always allowed.
3. Ideas still waiting for your OK expire.
4. **Shares the brain already bought are NOT sold.** Switching back stops new buying only. Version 1's usual stop-loss, target and time limit keep protecting those shares, or you can sell them yourself on the Positions page.

The same applies when you go from Automatic back to "Your OK needed": new buying then waits for you, and shares already bought stay protected as above.

## Switching the brain off completely

Go to the Strategies page and deactivate the **TradeMind brain** strategy. Its ideas then stop being recorded, and the brain stays advisory only. Shares already bought through it still keep version 1's protection until they are sold.

## Last resort

Version 1 is saved as the tag `v1` (commit `64fcb05`). It is the frozen point to return to if everything else fails.

## What Telegram sends

When ideas are waiting for your OK, you get one message in the evening listing them, with a link to the Brain page. There are no buttons in Telegram: approving and rejecting happen only on the Brain page.

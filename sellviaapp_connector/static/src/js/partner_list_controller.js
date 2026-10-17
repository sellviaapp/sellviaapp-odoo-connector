/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { useState } from "@odoo/owl";

export class SellViaAppPartnerListController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.sellViaAppSync = useState({ busy: false });
    }

    async _runSellViaAppAction(method, resIds) {
        if (this.sellViaAppSync.busy) {
            return;
        }
        this.sellViaAppSync.busy = true;
        try {
            const action = await this.orm.call(this.props.resModel, method, [resIds], {
                context: this.props.context,
            });
            if (action) {
                await this.actionService.doAction(action);
            }
            await this.model.root.load();
        } finally {
            this.sellViaAppSync.busy = false;
        }
    }

    async onSyncAllSellViaAppContacts() {
        await this._runSellViaAppAction("action_sellviaapp_sync_all_customers", []);
    }

    async onSyncSelectedSellViaAppContacts() {
        const resIds = await this.getSelectedResIds();
        if (resIds.length) {
            await this._runSellViaAppAction(
                "action_sellviaapp_sync_selected_customers",
                resIds
            );
        }
    }
}

export const sellViaAppPartnerListView = {
    ...listView,
    Controller: SellViaAppPartnerListController,
    buttonTemplate: "sellviaapp_connector.PartnerList.Buttons",
};

registry.category("views").add("sellviaapp_partner_list", sellViaAppPartnerListView);

"""Pre-effect reservations for the closed, canonical new record families."""
from .codec import ContextPackError,closed,encode,integer
from .types import _Record

TOOL_ENVELOPE_BYTES=1536
TOOL_ENVELOPE_NODES=64
FIXED_FAILURE_BYTES=4096
FIXED_FEEDBACK_BYTES=1024
FIXED_HEADROOM_NODES=256


def _nodes(value):
    stack=[value];count=0
    while stack:
        item=stack.pop();count+=1
        if type(item) is dict: stack.extend(item.values())
        elif type(item) is list: stack.extend(item)
    return count


class PackReservation(_Record):
    @classmethod
    def from_dict(cls,value):
        closed(value,{'version','family','encoding','stateBytes','receiptBytes','stateNodes','receiptNodes',
            'headroomBytes','headroomNodes','outputReservationBytes','toolResultReservationBytes',
            'maxStateBytes','maxReceiptBytes','maxJsonNodes','metadataBytes','eventBytes',
            'metadataNodes','eventNodes','outputBytes','toolResultBytes','providerAllowance',
            'userReservationBytes','userReservationNodes'})
        if type(value['version']) is not int or value['version']!=1 or value['family'] not in ('workflow','conversation') or value['encoding']!='json-sort-keys-utf8-v1':
            raise ContextPackError()
        for key,item in value.items():
            if key not in {'version','family','encoding','toolResultBytes'}: integer(item)
        if type(value['toolResultBytes']) is not list or len(value['toolResultBytes'])>256: raise ContextPackError()
        for amount in value['toolResultBytes']: integer(amount,1)
        copies=1 if value['family']=='workflow' else 2
        output=copies*(value['outputBytes']*6+2)
        tools=copies*sum(amount+TOOL_ENVELOPE_BYTES for amount in value['toolResultBytes'])
        expected_nodes=(copies+value['metadataNodes']+value['eventNodes']+FIXED_HEADROOM_NODES+
            copies*sum((amount+1)//2+1+TOOL_ENVELOPE_NODES for amount in value['toolResultBytes'])+value['userReservationNodes'])
        if (value['outputReservationBytes']!=output or value['toolResultReservationBytes']!=tools
                or value['headroomBytes']!=output+tools+value['metadataBytes']+value['eventBytes']+FIXED_FAILURE_BYTES+FIXED_FEEDBACK_BYTES+value['userReservationBytes']
                or value['headroomNodes']!=expected_nodes
                or value['eventNodes']<32*(value['providerAllowance']*2+len(value['toolResultBytes'])*2+2)
                or min(value['stateBytes'],value['receiptBytes'])<value['headroomBytes']
                or min(value['stateNodes'],value['receiptNodes'])<value['headroomNodes']):
            raise ContextPackError('contextBindingMismatch')
        if (value['stateBytes']>value['maxStateBytes'] or value['receiptBytes']>value['maxReceiptBytes']
                or max(value['stateNodes'],value['receiptNodes'])>value['maxJsonNodes']):
            raise ContextPackError('contextSnapshotLimit')
        result=object.__new__(cls);result._own(value,maximum=16384)
        return result


def reserve_pack_capacity(state,receipt,*,max_state_bytes,max_receipt_bytes,max_json_nodes=65536,
                          output_bytes=65536,metadata_bytes=65536,event_bytes=65536,
                          tool_result_bytes=(),family='workflow',metadata_nodes=2048,event_nodes=4096,
                          user_message=None,provider_allowance=8):
    """Count actual owned copies plus worst closed-profile output headroom.

    Workflow records retain one final Result and one tool-effect evidence copy;
    conversations also retain the portable exchange. Metadata/event node caps
    describe the admitted closed Runtime schemas, independently of byte caps.
    Controllers must enforce these same bounds on materialized records.
    """
    if type(family) is not str or family not in {'workflow','conversation'}: raise ContextPackError()
    for ceiling in (max_state_bytes,max_receipt_bytes,max_json_nodes): integer(ceiling,1)
    for amount in (output_bytes,metadata_bytes,event_bytes,metadata_nodes,event_nodes): integer(amount)
    integer(provider_allowance)
    if type(tool_result_bytes) not in (tuple,list) or len(tool_result_bytes)>256: raise ContextPackError()
    for amount in tool_result_bytes: integer(amount,1)
    if user_message is not None and type(user_message) is not str: raise ContextPackError()
    copies=1 if family=='workflow' else 2
    event_nodes=max(event_nodes,32*(provider_allowance*2+len(tool_result_bytes)*2+2))
    output_room=copies*(output_bytes*6+2)  # ASCII control characters have the largest JSON expansion.
    tool_room=copies*sum(amount+TOOL_ENVELOPE_BYTES for amount in tool_result_bytes)
    # A successful conversation exchange duplicates the exact current user;
    # the frozen input keeps its own independent copy as well.
    user_room=(len(encode({'role':'user','turnStatus':'completed','content':[{'type':'text','text':user_message}]}))
        if family=='conversation' and user_message is not None else 0)
    headroom=output_room+tool_room+metadata_bytes+event_bytes+FIXED_FAILURE_BYTES+FIXED_FEEDBACK_BYTES+user_room
    headroom_nodes=(copies+metadata_nodes+event_nodes+FIXED_HEADROOM_NODES+
        copies*sum((amount+1)//2+1+TOOL_ENVELOPE_NODES for amount in tool_result_bytes)+(8 if user_room else 0))
    try:
        state_size=len(encode(state,maximum=max_state_bytes,nodes=max_json_nodes))
        receipt_size=len(encode(receipt,maximum=max_receipt_bytes,nodes=max_json_nodes))
    except ContextPackError:
        raise ContextPackError('contextSnapshotLimit') from None
    document=dict(version=1,family=family,encoding='json-sort-keys-utf8-v1',
        stateBytes=state_size+headroom,receiptBytes=receipt_size+headroom,
        stateNodes=_nodes(state)+headroom_nodes,receiptNodes=_nodes(receipt)+headroom_nodes,
        headroomBytes=headroom,headroomNodes=headroom_nodes,outputReservationBytes=output_room,
        toolResultReservationBytes=tool_room,maxStateBytes=max_state_bytes,maxReceiptBytes=max_receipt_bytes,
        maxJsonNodes=max_json_nodes,metadataBytes=metadata_bytes,eventBytes=event_bytes,
        metadataNodes=metadata_nodes,eventNodes=event_nodes,outputBytes=output_bytes,
        toolResultBytes=list(tool_result_bytes),providerAllowance=provider_allowance,
        userReservationBytes=user_room,userReservationNodes=8 if user_room else 0)
    return PackReservation.from_dict(document)

# Complete corrected core/views.py file

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.db.models import Q, Count
from django.core.paginator import Paginator
from .models import (
    MemberOfParliament, VoteRecord, Bill, PolicyTopic,
    MPVote, Parliament, Committee
)


def home(request):
    """Homepage with search and overview"""
    context = {
        'total_mps': MemberOfParliament.objects.filter(status='ACTIVE').count(),
        'total_votes': VoteRecord.objects.count(),
        'total_bills': Bill.objects.count(),
        'policy_topics': PolicyTopic.objects.all()[:8],  # Featured topics
        'recent_votes': VoteRecord.objects.order_by('-vote_date')[:5],
    }
    return render(request, 'core/home.html', context)


def mp_list(request):
    """List all MPs with filtering and search"""
    mps = MemberOfParliament.objects.filter(status='ACTIVE')

    # Search functionality
    query = request.GET.get('q', '')
    if query:
        mps = mps.filter(
            Q(name__icontains=query) |
            Q(constituency__icontains=query) |
            Q(political_affiliation__icontains=query)
        )

    # Party filter
    party = request.GET.get('party', '')
    if party:
        mps = mps.filter(party_code=party)

    # Province filter
    province = request.GET.get('province', '')
    if province:
        mps = mps.filter(province=province)

    # Pagination
    paginator = Paginator(mps.order_by('name'), 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'query': query,
        'selected_party': party,
        'selected_province': province,
        'parties': MemberOfParliament.PARTY_CHOICES,
        'provinces': MemberOfParliament.objects.values_list('province', flat=True).distinct(),
    }
    return render(request, 'core/mp_list.html', context)


# Update your mp_detail view in core/views.py:

def mp_detail(request, mp_id):
    """Individual MP profile page with policy analysis"""
    mp = get_object_or_404(MemberOfParliament, id=mp_id)

    # Get recent votes
    recent_votes = MPVote.objects.filter(mp=mp).select_related('vote_record').order_by('-vote_record__vote_date')[:10]

    # Calculate policy stances
    policy_stances = {}
    try:
        from .scrapers import get_simple_mp_stance_for_frontend

        for topic in PolicyTopic.objects.all()[:8]:  # Limit for performance
            try:
                stance_data = get_simple_mp_stance_for_frontend(mp.id, topic.name)
                policy_stances[topic.name] = stance_data
            except:
                policy_stances[topic.name] = {
                    'stance': 'INSUFFICIENT_DATA',
                    'confidence': 'LOW',
                    'progressive_percentage': None
                }
        analysis_available = True
    except (ImportError, AttributeError):
        analysis_available = False

    context = {
        'mp': mp,
        'recent_votes': recent_votes,
        'vote_count': MPVote.objects.filter(mp=mp).count(),
        'policy_stances': policy_stances,
        'analysis_available': analysis_available,
    }
    return render(request, 'core/mp_detail.html', context)


def vote_list(request):
    """List all votes with filtering"""
    votes = VoteRecord.objects.all().order_by('-vote_date')

    # Search
    query = request.GET.get('q', '')
    if query:
        votes = votes.filter(subject__icontains=query)

    # Parliament filter
    parliament = request.GET.get('parliament', '')
    if parliament:
        votes = votes.filter(parliament__number=parliament)

    # Policy filter
    policy = request.GET.get('policy', '')
    if policy:
        # Handle JSONField search for SQLite compatibility
        votes = votes.filter(policy_tags__icontains=policy)

    # Pagination
    paginator = Paginator(votes, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'query': query,
        'selected_parliament': parliament,
        'selected_policy': policy,
        'parliaments': Parliament.objects.all(),
        'policy_topics': PolicyTopic.objects.all(),
    }
    return render(request, 'core/vote_list.html', context)


def vote_detail(request, vote_id):
    """Individual vote detail page"""
    vote = get_object_or_404(VoteRecord, id=vote_id)

    # Get MP votes with party breakdown
    mp_votes = MPVote.objects.filter(vote_record=vote).select_related('mp')

    # Party breakdown
    party_breakdown = {}
    for mp_vote in mp_votes:
        party = mp_vote.mp.political_affiliation
        if party not in party_breakdown:
            party_breakdown[party] = {'YEA': 0, 'NAY': 0, 'PAIRED': 0, 'ABSENT': 0}
        party_breakdown[party][mp_vote.vote] += 1

    context = {
        'vote': vote,
        'mp_votes': mp_votes,
        'party_breakdown': party_breakdown,
    }
    return render(request, 'core/vote_detail.html', context)


def compare_mps(request):
    """Policy-focused MP comparison page with caching"""
    selected_topics = request.GET.getlist('topics')
    all_topics = PolicyTopic.objects.all()

    context = {
        'all_topics': all_topics,
        'selected_topics': selected_topics,
    }

    if selected_topics:
        # Create cache key from selected topics
        cache_key = f"policy_analysis_{hashlib.md5(''.join(sorted(selected_topics)).encode()).hexdigest()}"

        # Try to get from cache first
        cached_data = cache.get(cache_key)
        if cached_data:
            print("Using cached policy analysis data")
            context.update(cached_data)
        else:
            print(f"Computing policy analysis for: {selected_topics}")

            # Limit the scope for better performance
            mps_by_party = {}
            major_parties = ['Conservative Party of Canada', 'Liberal Party of Canada', 'New Democratic Party']

            for party in major_parties:
                mps = MemberOfParliament.objects.filter(
                    status='ACTIVE',
                    political_affiliation=party
                )[:5]  # Limit to 5 MPs per party for testing
                mps_by_party[party] = list(mps)

            # Generate sample data (replace with real calculations later)
            import random
            topic_data = {}
            for topic_name in selected_topics[:3]:  # Limit to 3 topics max
                topic_data[topic_name] = {
                    'topic_name': topic_name,
                    'mps_positions': [],
                    'party_averages': {}
                }

                # Sample party averages
                for party in major_parties:
                    topic_data[topic_name]['party_averages'][party] = random.randint(20, 80)

                # Sample MP positions
                for party, mps in mps_by_party.items():
                    for mp in mps:
                        topic_data[topic_name]['mps_positions'].append({
                            'mp': mp,
                            'position': random.randint(10, 90),
                            'party': mp.political_affiliation,
                            'strength': random.choice(['Strong', 'Moderate', 'Weak'])
                        })

            cached_context = {
                'topic_data': topic_data,
                'mps_by_party': mps_by_party,
            }

            # Cache for 5 minutes
            cache.set(cache_key, cached_context, 300)
            context.update(cached_context)

    return render(request, 'core/compare_mps.html', context)

# API Views for AJAX requests
def api_mp_search(request):
    """API endpoint for MP search autocomplete"""
    query = request.GET.get('q', '')
    if len(query) < 2:
        return JsonResponse({'results': []})

    mps = MemberOfParliament.objects.filter(
        Q(name__icontains=query) | Q(constituency__icontains=query),
        status='ACTIVE'
    )[:10]

    results = [{
        'id': mp.id,
        'name': mp.name,
        'constituency': mp.constituency,
        'party': mp.political_affiliation
    } for mp in mps]

    return JsonResponse({'results': results})


def api_vote_search(request):
    """API endpoint for vote search"""
    query = request.GET.get('q', '')
    if len(query) < 3:
        return JsonResponse({'results': []})

    votes = VoteRecord.objects.filter(subject__icontains=query)[:10]

    results = [{
        'id': vote.id,
        'subject': vote.subject[:100] + '...' if len(vote.subject) > 100 else vote.subject,
        'date': vote.vote_date.strftime('%Y-%m-%d') if vote.vote_date else '',
        'result': vote.vote_result
    } for vote in votes]

    return JsonResponse({'results': results})